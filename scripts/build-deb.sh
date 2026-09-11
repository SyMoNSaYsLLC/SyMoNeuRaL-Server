#!/usr/bin/env bash
# Build the symoneural .deb from this checkout.
#
#     ./scripts/build-deb.sh [-o OUTDIR]        # default OUTDIR is ~/Downloads
#     ./scripts/build-deb.sh --list             # print the exact shipping manifest only
#
# Needs no root: the payload is staged with `fakeroot`-free `dpkg-deb --root-owner-group`,
# which writes root:root ownership into the archive without becoming root.
#
# The first two .deb files in this project were assembled by hand at a shell prompt. That
# worked twice and is why this file exists: the contents were decided in the moment, the
# exclusions lived in a scrollback buffer, and nothing recorded why `training/corpus.jsonl`
# was absent. The exclusion list below is the same one, written down and asserted.
#
# WHAT IS IN IT: tracked production files, minus protected and non-production exclusions.
# Tracked-ness is the first rule because
# `.gitignore` already encodes "build output, weights and secrets do not travel" -- the
# 104 GiB of `models/`, every `.venv`, `contrib/`, `engines/`, `external/`, `run/`.
# Using `git ls-files` rather than `find` means those cannot be re-included by accident.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }
cd "$ROOT"

OUT="$HOME/Downloads"
LIST_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output) OUT="$2"; shift 2;;
    --list) LIST_ONLY=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

# --- version -----------------------------------------------------------------
# It must be MONOTONIC, or `apt upgrade` will not offer it. A bare commit SHA is not:
# dpkg compares version strings component-wise, so `a5c11b8` sorts above `df1d862`
# (letters before digits in dpkg's ordering) and a later build would look older. The
# date leads, the commit COUNT breaks ties within a day, and the SHA is identification
# only -- it never decides the comparison.
SHA="$(git rev-parse --short HEAD)"
COUNT="$(git rev-list --count HEAD)"
STAMP="$(git log -1 --format=%cd --date=format:%Y%m%d)"
VERSION="0.1.0+git${STAMP}.r${COUNT}.g${SHA}"
DIRTY=""
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  DIRTY=" (tracked tree is DIRTY -- this package does not match any commit)"
fi

PKG="symoneural_${VERSION}_all"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
DEST="$STAGE/$PKG"
mkdir -p "$DEST/DEBIAN" "$DEST/opt/symoneural" "$DEST/usr/bin" "$DEST/usr/share/doc/symoneural"

# --- what does not travel ----------------------------------------------------
# Each line is a reason, not a preference:
#
#  training/corpus.jsonl, build_dataset.py, project-history/build_history_corpus.py, adapter*/
#      The trade secret. `.claude/CLAUDE.md`: "never copy any of these into site/, never serve
#      them from an endpoint". A .deb is a copy that leaves the box, which is the same problem
#      with a different verb. The two adapter directories carry only their configs in git (the
#      weights are gitignored), but a `adapter_config.json` naming the rank and target modules
#      is part of the method.
#  backend/remix/.env
#      Tracked, and carries live-looking secrets. The v1 .deb shipped it. That is the single
#      concrete reason this script exists rather than another hand-rolled `cp -r`.
#  .claude/
#      Internal working documents, including HANDOVER.md, which names what is proprietary.
#  .github/, .gitignore
#      Repository mechanics, meaningless in /opt.
EXCLUDE_RE='^(training/(corpus\.jsonl|build_dataset\.py|project-history/|adapter)'
EXCLUDE_RE="$EXCLUDE_RE"'|backend/remix/\.env$|\.claude/|\.github/|\.gitignore$)'

# Source that is useful in the repository but is not part of the main runtime package.
# Nothing is deleted from the checkout. Separate deliverables keep their own source; test
# and reference trees stay available to Coder without becoming customer payload.
#
#  archive/vendor-sdks/       adopted SDK/reference source; no serving module imports it
#  deploy/bento/         explicitly non-live alternate serving experiment
#  desktop-client/, yocto/
#                        separate build/package targets, not Python runtime payload
#  garbo/, incoming/     review/import staging records
#  tests and test_*.py   verification source, never imported by the running product
#  root work ledgers     agent/review state rather than product or operator docs
NONPROD_RE='^(archive/vendor-sdks/|deploy/bento/|desktop-client/|yocto/|garbo/|incoming/|tests/)'
# `.mjs` as well as `.py`: `backend/studio/plugins/reinforce/test_page.mjs` and
# `ops/gateway/test_contracts.mjs` both shipped in the manifest while this rule read `.py`
# only -- measured with `--list`. A rule that names one extension of a two-extension test
# suite excludes the half you happened to think of.
NONPROD_RE="$NONPROD_RE"'|(^|/)tests/|(^|/)test_[^/]*\.(py|mjs)$'
NONPROD_RE="$NONPROD_RE"'|^(AUDIT-SURFACE-[^/]*|CLAUDE\.md|GARRETT-INBOX\.md|GUARDRAILS\.md|PROJECT-TASKS\.md|\.mailmap)$'

git ls-files -z | tr '\0' '\n' | grep -Ev "$EXCLUDE_RE|$NONPROD_RE" > "$STAGE/manifest.txt"
FILES="$(wc -l < "$STAGE/manifest.txt")"

if [ "$LIST_ONLY" -eq 1 ]; then
  cat "$STAGE/manifest.txt"
  exit 0
fi

mkdir -p "$OUT"
command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found" >&2; exit 1; }

# Copy with the tree structure intact. `--parents` is what keeps backend/... nested
# rather than flattening 645 files into one directory.
tr '\n' '\0' < "$STAGE/manifest.txt" | xargs -0 cp --parents -t "$DEST/opt/symoneural"

# A guard, not a comment: every excluded path must be absent from the staged payload. The
# v1 .deb shipped a secrets file precisely because nothing checked. This is that check.
#
# It used to be an inline loop here, naming five paths and two directories. It is now the
# shared function, for one reason: this was one of three packaging paths and the only one
# that had a check. A check inside one script protects one script, and a copied check
# drifts -- this list gained `training/project-history/` when that landed, and a copy
# elsewhere would not have. `shareable` is the correct mode: a .deb leaves the box.
. "$ROOT/scripts/lib/archive-guard.sh"
archive_guard shareable "$DEST/opt/symoneural" "the .deb payload" \
  || { echo "refusing to build" >&2; exit 1; }

cp README.md "$DEST/usr/share/doc/symoneural/README.md"
ln -s /opt/symoneural/bin/symoneural-cli "$DEST/usr/bin/symoneural-cli"
chmod 0755 "$DEST/opt/symoneural/bin/symoneural-cli"
find "$DEST/opt/symoneural/scripts" -name '*.sh' -exec chmod 0755 {} +

SIZE_KB="$(du -sk "$DEST" | cut -f1)"

# --- control -----------------------------------------------------------------
cat > "$DEST/DEBIAN/control" <<CONTROL
Package: symoneural
Version: $VERSION
Section: science
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-sympy, python3-httpx, python3-fastapi, python3-uvicorn
Recommends: caddy
Suggests: nvidia-cuda-toolkit
Installed-Size: $SIZE_KB
Maintainer: Garrett McDonald <gmcdonald@symoneural.com>
Homepage: https://symoneural.com
Description: SyMoNeuRaL local AI stack -- CLI, API, site and studio tools
 One workstation serving chat, image generation and exact symbolic mathematics from
 local weights, with a single GPU arbitrated by a governor rather than shared.
 .
 This package installs the Python sources, the site, the build tools and the
 operator CLI to /opt/symoneural, and puts symoneural-cli on PATH. It installs no
 systemd unit and starts nothing.
 .
 On upgrade it republishes the site to /var/www/symoneural if that webroot already
 exists, which is the packaged equivalent of "sudo scripts/deploy.sh --prune". On a
 host with no webroot it deploys nothing and says so. Create
 /etc/symoneural/no-auto-deploy to suppress it.
 .
 Model weights are NOT included: they are roughly 104 GiB on the reference box and
 are fetched separately into models. The llama.cpp and stable-diffusion.cpp
 binaries are not included either -- they are built from contrib/ on the target,
 against its own driver and compute capability. Until both exist,
 "symoneural-cli status" reports the surfaces as not built, which is accurate.
 .
 The trained LoRA adapter, its training corpus and both corpus builders are
 deliberately excluded from this package, and the build refuses to run if any of
 them reaches the payload.
CONTROL

# --- postinst ----------------------------------------------------------------
# This is the "sudo apt upgrade does the deploy" half of the feature. It runs as root
# already, so there is no re-exec here.
#
# On the exit status: a failed deploy does NOT fail the package. dpkg would leave
# symoneural half-configured and every later apt command would demand
# `dpkg --configure -a`, which is a worse outcome than a site that needs one more
# command. But "printed a warning" is not a mechanism -- so the failure is also
# recorded in /var/lib/symoneural/last-deploy, which `symoneural-cli upgrade` and
# `symoneural-cli status` both read back.
cat > "$DEST/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

STATE=/var/lib/symoneural
WEBROOT=/var/www/symoneural
DEPLOY=/opt/symoneural/scripts/deploy.sh

if [ "$1" != "configure" ]; then
    exit 0
fi

printf 'symoneural: installed to /opt/symoneural\n'
printf '  symoneural-cli status      the card, the surfaces and the governor lock\n'
printf '  symoneural-cli upgrade     republish the site and restart the service\n'
printf '  symoneural-cli tools       the studio tools the agent is handed\n'
printf '  symoneural-cli mcp         the MCP transport, and how a client wires it\n'
printf 'No weights and no built binaries ship here; status will say so until they exist.\n'

mkdir -p "$STATE"

if [ -e /etc/symoneural/no-auto-deploy ]; then
    printf 'symoneural: /etc/symoneural/no-auto-deploy exists -- not touching the webroot.\n'
    echo "skipped: no-auto-deploy" > "$STATE/last-deploy"
    exit 0
fi

# A webroot is only ours to prune if it looks like ours. An empty or foreign
# /var/www/symoneural would have every file in it reported as an orphan and deleted.
if [ ! -f "$WEBROOT/index.html" ] || [ ! -f "$WEBROOT/symoneural.css" ]; then
    printf 'symoneural: no deployed site at %s -- nothing republished.\n' "$WEBROOT"
    printf '            after the first deploy, apt upgrade will keep it current:\n'
    printf '              sudo %s --prune\n' "$DEPLOY"
    echo "skipped: no existing webroot at $WEBROOT" > "$STATE/last-deploy"
    exit 0
fi

printf 'symoneural: republishing the site to %s\n' "$WEBROOT"
if "$DEPLOY" --prune > "$STATE/last-deploy.log" 2>&1; then
    tail -n 3 "$STATE/last-deploy.log" | sed 's/^/  /'
    echo "ok: $(date -Is)" > "$STATE/last-deploy"
else
    printf '\n'
    printf '  ***********************************************************************\n'
    printf '  * THE PACKAGE INSTALLED BUT THE SITE DEPLOY FAILED.                   *\n'
    printf '  * Log: %-62s *\n' "$STATE/last-deploy.log"
    printf '  * Re-run by hand:  sudo %-45s *\n' "$DEPLOY --prune"
    printf '  ***********************************************************************\n'
    tail -n 15 "$STATE/last-deploy.log" | sed 's/^/  | /'
    echo "FAILED: $(date -Is) -- see $STATE/last-deploy.log" > "$STATE/last-deploy"
fi

# The API is restarted only if this host actually runs it as a service. `is-active`,
# which is what the line below asks: a unit that is enabled but deliberately stopped must
# stay stopped, and `restart` would start it. (This comment said `is-enabled` for as long
# as the code said `is-active`, and then argued for the behaviour the code already had.)
if command -v systemctl >/dev/null 2>&1 \
   && systemctl is-active --quiet symoneural-api 2>/dev/null; then
    printf 'symoneural: restarting symoneural-api\n'
    systemctl restart symoneural-api \
        || printf '  restart failed -- check journalctl -u symoneural-api\n'
fi

exit 0
POSTINST
chmod 0755 "$DEST/DEBIAN/postinst"

# --- build -------------------------------------------------------------------
dpkg-deb --root-owner-group -Zxz -b "$DEST" "$OUT/$PKG.deb" >/dev/null
BUILT="$OUT/$PKG.deb"

echo "built    $BUILT"
echo "version  $VERSION$DIRTY"
echo "payload  $FILES files, ${SIZE_KB} KiB installed"
echo
echo "verify:  dpkg-deb -I '$BUILT'"
echo "install: sudo apt install '$BUILT'      # apt, not dpkg -i, so Depends resolve"
