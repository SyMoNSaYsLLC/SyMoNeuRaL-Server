#!/usr/bin/env bash
# Publish the staged site to /var/www/symoneural.
#
# Needs root because the webroot is www-data owned. Run it with sudo:
#     sudo ./deploy.sh          (from the repo root)
#
# Backs up the current index.html to a fresh timestamped name every time.
#
# THE ONLY FILE THIS SCRIPT PROTECTS IS THE BACKUP IT TOOK ON THIS RUN. Everything else in
# the webroot without a counterpart in site/ is an orphan, and `--prune` deletes it. There is
# no allowlist, and adding one is not the fix -- see below.
#
# This header used to promise something else: "it never touches index.backup-20260816-141604
# .html -- that is the 419 KB original training page and the only copy of it." That was true
# when the script only ever copied. `a344005` added the orphan scan and `--prune`, and the
# exemption it names was never implemented -- the loop exempts `index.prev-$STAMP.html` and
# nothing more. That file had no counterpart in site/ and was never tracked in git (checked:
# `git log --all -- '*index.backup-20260816*'` is empty; it existed only in the webroot), so
# it was listed as an orphan and a later `--prune` removed it. It is now gone from the
# webroot, from site/ and from everywhere under /home/google. Confirmed 2026-08-17.
#
# Not restored, and not re-exempted, deliberately. It was the old MIT AI Training page, and
# that branding is purged everywhere user-facing -- an exemption for a filename that no
# longer exists is dead code that reads as a live guarantee. The lesson is the general one:
# **a comment promising a file is safe is not a mechanism.** If a webroot file must survive
# a prune, it belongs in the loop as code or outside the webroot entirely, and the only
# reason this one was lost is that a sentence stood in for both.
set -euo pipefail

# Repo root, not its parent. This climbed one level when the script lived in demo/;
# after the flatten it resolved to /home/google/MIT_AI_Training/site, which does not
# exist, so every deploy exited with "no staged site" and the live site stayed stale.
# Repo root is one level up now that this lives in scripts/. This calculation has
# been wrong three times in this repo (the demo/ flatten, the tools/ move, here) and
# it fails silently, because the wrong parent is usually a directory that exists.
# The guard below turns that into an immediate, obvious failure.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT (expected backend/server.py)" >&2; exit 1; }
SRC="$ROOT/site"
DST=/var/www/symoneural
STAMP="$(date +%Y%m%d-%H%M%S)"

[ -d "$SRC" ] || { echo "no staged site at $SRC" >&2; exit 1; }
[ -d "$DST" ] || { echo "no webroot at $DST" >&2; exit 1; }

# Only real web assets are published. `find -type f` used to publish whatever happened to
# be sitting in site/, and what was sitting in site/ was an 11.6 MB browser "Save page as"
# capture of the site plus its PDF print -- dropped there to show what a broken deploy
# looked like. Those would have gone straight into the public webroot. The staging
# directory is a working directory; the webroot is not.
#
# .json is deliberately absent. The only .json a page could want is /openapi.json, and Caddy
# proxies that to FastAPI, which generates it -- a static copy would be shadowed and go
# stale. The other twenty are art-*.json, build-time metadata that tools/build_band.py reads
# to print each prompt into the page; nothing fetches them. Both are already handled: the
# reference check below treats openapi.json as a route, and no page links an art-*.json.
#
# Alternatives are ordered longest-first where one is a prefix of another. `js` before
# `json` silently dropped every .json file: find's -regex must match the whole path, `js`
# matched, the trailing `on` did not, and it did not back up to try `json`.
PUBLISH='.*\.\(html\|css\|jpeg\|jpg\|js\|png\|svg\|ico\|webp\|woff2\|txt\|xml\)'
skipped="$(find "$SRC" -maxdepth 1 -type f ! -regex "$PUBLISH" -printf '%f\n' | sort)"
echo "staged:  $SRC  ($(find "$SRC" -maxdepth 1 -type f -regex "$PUBLISH" | wc -l) files)"
if [ -n "$skipped" ]; then
  echo "skipped: not a web asset --"
  printf '  %s\n' $skipped
fi

if [ -f "$DST/index.html" ]; then
  cp -p "$DST/index.html" "$DST/index.prev-$STAMP.html"
  echo "backup:  index.prev-$STAMP.html"
fi

# Top-level files.
find "$SRC" -maxdepth 1 -type f -regex "$PUBLISH" \
  -exec install -o www-data -g www-data -m 644 {} "$DST/" \;

# There is deliberately no /docs case here any more. Caddy proxies /docs and /openapi.json
# to FastAPI, which generates them, so a static copy in the webroot would be shadowed by the
# proxy and would only ever go stale. It was also the last piece of routing living outside
# the API, which is the thing this deployment is not supposed to do.
echo "deployed to $DST"


# --- orphans -----------------------------------------------------------------
# This script copies; it has never deleted. So every rename leaves its old file in the
# webroot forever: 19 generated renders (13 MB) that moved to backend/output/, six
# superseded index backups, and a static docs/ directory that Caddy now shadows by
# proxying /docs to FastAPI. Report them every time, delete only when asked.
echo
echo "checking for files in the webroot that are no longer in site/:"
orphans=0
orphan_list="$(mktemp)"
# An orphan is a webroot file that this deploy would not have published -- tested against
# the same PUBLISH filter, not merely against "does it exist in site/". Those differ now
# that site/ is allowed to hold files the webroot must not: openapi.json is proxied to
# FastAPI, and the art-*.json are build-time metadata. Testing presence alone would leave
# every already-published copy of them in the webroot forever, never updated, never removed.
#
# The backup taken at the top of this run is exempt. It is written into the webroot and has
# no counterpart in site/, so a naive check prunes the one file that exists to undo a bad
# deploy, in the same run that created it.
find "$DST" -maxdepth 1 -type f -printf '%f\n' | sort | while read -r f; do
  [ "$f" = "index.prev-$STAMP.html" ] && continue
  if [ -f "$SRC/$f" ] && printf '%s\n' "$SRC/$f" | grep -qx -e "$PUBLISH"; then
    continue
  fi
  echo "$f"
done > "$orphan_list"
orphans="$(wc -l < "$orphan_list")"

if [ "$orphans" -eq 0 ] && [ ! -d "$DST/docs" ]; then
  echo "  none"
else
  sed 's/^/  orphan  /' "$orphan_list"
  [ -d "$DST/docs" ] && echo "  orphan  docs/            (a directory -- /docs is proxied to the API now)"
  if [ "${1:-}" = "--prune" ]; then
    echo
    while read -r f; do rm -f -- "$DST/$f"; done < "$orphan_list"
    [ -d "$DST/docs" ] && rm -rf -- "$DST/docs"
    echo "  pruned $orphans file(s)$([ -d "$DST/docs" ] || echo ' and docs/')"
  else
    echo
    echo "  left in place. Remove them with:  sudo $0 --prune"
  fi
fi
rm -f "$orphan_list"

# Orphans are removed BEFORE the reference check, not after. The check tests $DST, so a
# page referencing a file that lives only in the webroot would be reported "ok" and then
# deleted by the prune in the same run -- the check passing on a state that no longer
# exists by the time the script exits. Pruning first means it verifies what is actually
# being served.
echo
echo "verifying every local asset reference resolves on disk:"
# Fragment links (href="/#build") are in-page anchors, not files -- excluding '#' keeps
# them out of the report instead of listing three permanent phantom failures that train
# the reader to ignore the whole check.
#
# This used to pipe into `while read`, which runs in a subshell, so the `missing=1` set
# inside it was discarded and the script could print MISSING lines and still exit 0. The
# whole point of a verification step is that it can fail, so the loop reads from a process
# substitution and the count survives.
missing=0
# Routes FastAPI serves through the proxy are not files and never will be. Checking them
# with -f produced "MISSING docs" on a deploy where /docs was answering 200 from uvicorn --
# a check that cries wolf is worse than no check, because the next real failure gets ignored.
#
# The four front-page sections belong in this list for exactly the same reason as docs.
# tools/build/build_split.py writes them as overview.html, livestack.html and so on, but every
# page links them WITHOUT the extension because ops/Caddyfile reverse-proxies those paths
# to FastAPI. So `/livestack` is a real, working URL that is correctly not a file, and
# checking it with -f reported MISSING on a deploy where all four answered 200.
#
# Note the asymmetry this list encodes: `livestack` is a route, `livestack.html` is a file,
# and both resolve. Only the extensionless form is exempted here, so a genuinely missing
# livestack.html is still caught.
# `studio` and `exp` are the same case again and were reported MISSING on a deploy where both
# answered 200 -- so this check was failing every deploy, and `deploy.sh` exits non-zero when
# it does. That is not a cosmetic wolf-cry: ops/units/symoneural-deploy.service deliberately carries
# no SuccessExitStatus, so an unattended boot-time deploy would have gone red every time.
#
# Checked before being added, because the whole value of this list is that nothing goes in it
# that is genuinely absent: both are `@app.get(..., include_in_schema=False)` in backend/server.py
# (/studio at :2616, /exp at :2635), both are named in ops/Caddyfile's @studio and @exp
# matchers, and both answered 200 on the running service. site/index.html links them
# extensionless at :265 and :272.
#
# They differ from the four above in one way worth knowing: livestack IS also livestack.html on
# disk, whereas there is no studio.html or exp.html and never was -- these render from the API
# only. So the asymmetry note above does not apply to them; there is no file form to catch.
# `livestack/live` is the THIRD time this list has failed a working deploy, and the first
# two-segment page route in the repo. Measured 2026-08-21: `MISSING livestack/live`, exit 1,
# while the path answered 200. Verified all three ways before adding, per the paragraph above:
# `@app.get("/livestack/live", include_in_schema=False)` at backend/server.py:2969, its own
# `@live path /livestack/live` matcher in ops/Caddyfile, and 200 on the running service.
#
# Listed as the exact path, NOT as `livestack/*`. A glob would exempt every future child of
# /livestack -- including a typo -- and exempting a path is how this check stops catching the
# absent file it exists for. There is no `livestack/live.html` on disk to be masked: the file
# is `site/live.html`, which the mount answers at `/live.html` and which this loop still
# checks under that name.
#
# apps/test_deploy_routes.py was written to make this class of rot go red and did not, which
# is worth more than the one-line fix: its route regex matched a single path segment, so a
# two-segment route was never parsed out of api.py and never reached the comparison. Both
# regexes are multi-segment now and there is a narrow shape guard beside them.
is_route() {
  case "$1" in
    docs|docs/*|openapi.json|api|api/*) return 0;;
    overview|livestack|controlboard|receipts) return 0;;
    studio|exp) return 0;;
    livestack/live|live-stack/live) return 0;;
    # Both spellings of the Coder page. api.py serves one page at both and redirects
    # neither, so both are routes and neither is ever a file. `coder.html` deliberately
    # does NOT appear here -- the page IS a real file in the webroot and a missing one
    # must still be reported, which is the same asymmetry `livestack` documents above.
    live-stack/coder|livestack/coder) return 0;;
    # #81's application pages, both spellings, from backend/server.py's LIVESTACK_PAGES.
    # Listed EXACTLY and never as `livestack/*`: a wildcard would also exempt
    # `livestack/image.html`, `livestack/anything.js` and every future typo'd reference
    # under that prefix, and an exemption that over-matches stops the check catching a
    # genuinely absent file -- which is the whole failure mode this function's comments
    # keep returning to. apps/test_deploy_routes.py asserts both directions.
    live-stack/image|livestack/image) return 0;;
    # The DispatchOS application page. Listed for the fourth time this function has been
    # taught a working route -- and the first one declared on an app's OWN router
    # (`apps/dispatchos/routes.py`, `@ui_router.get("/demo/dispatchos")`) rather than as a
    # literal `@app.get` in backend/server.py. It arrived in the published markup on 2026-08-29,
    # when `dispatchos` was finally written into ROSTER.md and the generated pre-JS rack
    # fallback grew an `<a class="unit" href="/demo/dispatchos">`.
    #
    # Without this line the reference check reports `MISSING demo/dispatchos` and exits 1 on a
    # deploy where the path answers 200 -- and `ops/units/symoneural-deploy.service` deliberately
    # carries no SuccessExitStatus, so the boot-time publish would have gone red every time.
    # Exactly the failure the four paragraphs above this function describe, arriving again.
    #
    # Exact path, never `demo/*`: a glob would exempt every future child of /demo including a
    # typo, and an exemption that over-matches stops this check catching a genuinely absent
    # file, which is the whole point of it.
    # `/demo/dispatchos/docs` is the customer-scoped documentation page, served by the same
    # router behind the same Caddy door. Nothing in site/ links it today -- the DispatchOS
    # page is rendered BY the API and never published -- so it cannot currently reach this
    # check. Listed anyway, and deliberately: the alternative is that the day somebody links
    # it from a published page, a working route becomes `MISSING` and takes the boot-time
    # deploy red. Cheap now, silent failure later.
    demo/dispatchos|demo/dispatchos/docs) return 0;;
    *) return 1;;
  esac
}
while read -r ref; do
  if is_route "$ref"; then
    printf '  route   %s (served by the API)\n' "$ref"
  elif [ -f "$DST/$ref" ]; then
    printf '  ok      %s\n' "$ref"
  else
    printf '  MISSING %s\n' "$ref"; missing=$((missing + 1))
  fi
#
# The `?v=<hash>` cache-busting suffix is stripped before the file is looked up. Without
# that, every stylesheet and script reference became "MISSING symoneural.css?v=90b254cb57"
# and the script exited 1 on a deploy that was completely correct -- a verification step
# that fails on healthy input gets switched off, and then it protects nothing.
done < <(grep -ohE '(src|href)="/[^"#]+"' "$DST"/*.html \
         | sed 's/.*"\/\(.*\)"/\1/' | sed 's/?.*$//' | sort -u)

echo
if [ "$missing" -gt 0 ]; then
  echo "FAILED: $missing referenced asset(s) are not on disk. The site is deployed but"
  echo "incomplete -- fix the reference or ship the file, then re-run."
  exit 1
fi
echo "done. reload https://symoneural.com/ with a hard refresh."
