#!/usr/bin/env bash
# Build the SyMoNeuRaL gateway for THIS Debian host, reproducibly, from canonical source.
#
#   ops/build-gateway.sh              build if the binary is missing or stale
#   ops/build-gateway.sh --force      rebuild unconditionally
#   ops/build-gateway.sh --check      report what would happen; build nothing
#
# ## Why a NATIVE build and not the Yocto SDK -- measured, not assumed
#
# Garrett's rule: *"Build from /yocto when appropriate, but never require /yocto at
# runtime"*, together with: never install a target binary on the Debian host without proving
# its interpreter, ABI, dependencies and runtime compatibility.
#
# The extensible SDK that exists on this box was read rather than guessed at, from its own
# `…toolchain-0.1.0.testdata.json` in `/yocto/build-symoneural/tmp-arm64-*/deploy/sdk`:
#
#     SDK_SYS                    x86_64-oesdk-linux      <- the machine that RUNS the compiler
#     TARGET_SYS                 aarch64-oe-linux        <- what it COMPILES FOR
#     TARGET_ARCH                aarch64
#     MACHINE                    symoneural-arm64
#     TCLIBC                     glibc
#     SDKPATH                    /usr/local/oe-sdk-hardcoded-buildpath
#
# The live host is `x86_64-linux-gnu`, Debian 13.6. **The SDK's target is aarch64, so it
# cannot produce a binary that runs here at all** -- this is case 2 of the component
# decision: the SDK is for a separate SyMoNeuRaL image, and the Debian-host artifact comes
# from a separate reproducible native build of the same canonical source. Being both
# "x86-64" is not the question; the SDK is x86-64 on the *host* side and aarch64 on the
# *target* side, and the target side is what lands in a binary.
#
# So this uses the Debian toolchain, verified present at build time and recorded in the
# build record: cargo/rustc from Debian, linking against the host's own glibc.
#
# ## What it refuses to do
#
# It will not write outside the repository, will not touch /yocto, and will not install
# anything into /etc. Installation is `ops/install-runtime.sh`'s job, deliberately separated
# so a build can be run and inspected without a service restart anywhere near it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }

SRC="$ROOT/backend/gateway"
RECORD="$ROOT/ops/manifests/gateway-build.json"

# ---------------------------------------------------------------- what is being built
#
# ## `OUT` is DERIVED, because the literal it replaced went stale and re-staled the manifest
#
# This said `OUT="$SRC/target/release/symon-gateway"`. The crate was renamed to
# `symoneural-gateway` on 2026-08-26 -- the runtime-identity contract requires first-party
# executables to begin with `symoneural-`, and this binary was the one live violation -- and
# this line was not moved with it. The result was not a build failure, which is what makes it
# worth this many words:
#
#   cargo emitted target/release/symoneural-gateway, as Cargo.toml told it to;
#   the superseded target/release/symon-gateway was STILL ON DISK from the previous build;
#   `[ -f "$OUT" ]` therefore passed;
#   and everything below hashed, proved and RECORDED a binary cargo had not just produced.
#
# So the builder would report a successful build and write a build record describing the
# artifact it had just superseded. `ops/manifests/gateway-build.json` was in exactly that
# state for three days.
#
# Cargo's output name comes from `[[bin]] name` and from nothing else, so that is the only
# honest source for this. It is NOT read from the manifest: the manifest records what was
# built, Cargo.toml determines what will be, and deriving the second from the first inverts
# the dependency and would let a stale manifest dictate the build.
BIN_NAME="$(python3 - "$SRC/Cargo.toml" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r'^\[\[bin\]\](.*?)(?=^\[|\Z)', src, re.M | re.S)
section = m.group(1) if m else src.split("[dependencies]")[0]
n = re.search(r'^\s*name\s*=\s*"([^"]+)"', section, re.M)
print(n.group(1) if n else "")
PY
)"
[ -n "$BIN_NAME" ] || { echo "  cannot read the binary name from $SRC/Cargo.toml" >&2; exit 1; }
OUT="$SRC/target/release/$BIN_NAME"

# The manifest must name the same artifact. These are two independent statements of one
# identity -- Cargo.toml says what gets produced, the manifest says what is canonical -- and
# a build that quietly writes a record about a different filename is the failure above.
[ -f "$RECORD" ] || {
    echo "  no build record at $RECORD." >&2
    echo "  This script UPDATES that record; it does not invent one, because a record with no" >&2
    echo "  provenance fields is a claim nobody made. Restore it from git first." >&2
    exit 1; }
RECORD_NAME="$(python3 -c 'import json,sys,os; print(os.path.basename(json.load(open(sys.argv[1]))["relative_path"]))' "$RECORD")"
if [ "$BIN_NAME" != "$RECORD_NAME" ]; then
    echo "  REFUSING: Cargo.toml builds '$BIN_NAME' but $RECORD names '$RECORD_NAME'." >&2
    echo "  One of the two is stale. Building would record the wrong artifact -- which is" >&2
    echo "  precisely how this record came to describe a superseded binary for three days." >&2
    exit 1
fi

MODE=build
case "${1:-}" in
    --force) MODE=force ;;
    --check) MODE=check ;;
    "")      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
esac

say() { printf '  %s\n' "$*"; }

# ---------------------------------------------------------------- toolchain
say "toolchain (Debian native, not the SDK):"
for t in cargo rustc cc; do
    command -v "$t" >/dev/null || { echo "  MISSING: $t -- install the Debian toolchain" >&2; exit 1; }
    say "  $(printf '%-6s' "$t") $($t --version 2>&1 | head -1)"
done
HOST_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
say "  rustc host triple: $HOST_TRIPLE"
case "$HOST_TRIPLE" in
    x86_64-unknown-linux-gnu) ;;
    *) echo "  refusing: rustc host triple is $HOST_TRIPLE, expected x86_64-unknown-linux-gnu" >&2; exit 1 ;;
esac

[ -f "$SRC/Cargo.toml" ] || { echo "  no Cargo.toml at $SRC" >&2; exit 1; }

if [ "$MODE" = check ]; then
    say "check only -- nothing built."
    [ -f "$OUT" ] && say "existing binary: $(stat -c '%s bytes, mtime %y' "$OUT")" || say "no existing binary"
    exit 0
fi

# ---------------------------------------------------------------- build
# `--locked` so the build is reproducible from Cargo.lock rather than from whatever crates.io
# happens to offer today. If the lock file is missing or stale the build FAILS instead of
# quietly resolving something else, which is the whole point of calling this reproducible.
LOCKED=--locked
[ -f "$SRC/Cargo.lock" ] || { say "no Cargo.lock -- building without --locked (NOT reproducible)"; LOCKED=; }

say "building (cargo build --release $LOCKED) ..."
BUILD_STARTED="$(date +%s)"
( cd "$SRC" && CARGO_TERM_COLOR=never cargo build --release $LOCKED ) || {
    echo "  BUILD FAILED -- the existing binary was left untouched" >&2; exit 1; }

[ -f "$OUT" ] || { echo "  build reported success but $OUT is absent" >&2; exit 1; }

# Existence is not freshness. The name-drift above was one instance of a general bug -- cargo
# reporting success while the file this script goes on to hash was produced by some earlier
# run -- and deriving OUT correctly closes that instance without closing the class. A binary
# older than the build that supposedly made it is the reading that catches the rest.
if [ "$(stat -c %Y "$OUT")" -lt "$BUILD_STARTED" ]; then
    echo "  REFUSING: cargo reported success but $OUT is older than the build." >&2
    echo "  mtime $(stat -c %y "$OUT"), build started $(date -d @"$BUILD_STARTED" -Is)." >&2
    echo "  Whatever cargo produced, it was not this file, and recording it would attribute" >&2
    echo "  a build to an artifact that did not come from it." >&2
    exit 1
fi

# ---------------------------------------------------------------- independence
# Cargo hardlinks target/release/<name> from target/release/deps/<name>-<hash>, so the
# freshly built file has st_nlink=2. The runtime contract asks for an INDEPENDENT regular
# file, so the link is broken here rather than left for somebody to notice in an audit.
# Content is unchanged and verified so.
BEFORE="$(sha256sum "$OUT" | cut -d' ' -f1)"
if [ "$(stat -c %h "$OUT")" -gt 1 ]; then
    cp -p "$OUT" "$OUT.tmp$$" && mv -f "$OUT.tmp$$" "$OUT"
    say "broke cargo's hardlink; st_nlink is now $(stat -c %h "$OUT")"
fi
AFTER="$(sha256sum "$OUT" | cut -d' ' -f1)"
[ "$BEFORE" = "$AFTER" ] || { echo "  content changed while breaking the hardlink -- refusing" >&2; exit 1; }

# ---------------------------------------------------------------- prove the artifact
say "artifact:"
say "  path      $OUT"
say "  size      $(stat -c %s "$OUT") bytes"
say "  sha256    $AFTER"
say "  links     $(stat -c %h "$OUT")"
# `|| true` on every grep here, and it is not defensive noise. This script runs under
# `set -e` with `pipefail`, and a binary with NO RPATH is the healthy case -- `grep RPATH`
# then exits 1, the assignment inherits it, and the script dies silently at the exact moment
# it is about to report a clean result. That happened on the first run: the build succeeded,
# the artifact was correct, and the build record was never written.
INTERP="$(readelf -l "$OUT" 2>/dev/null | sed -n 's/.*interpreter: \(.*\)\]/\1/p' || true)"
RPATH="$(readelf -d "$OUT" 2>/dev/null | grep RPATH | sed 's/.*\[\(.*\)\]/\1/' || true)"
RUNPATH="$(readelf -d "$OUT" 2>/dev/null | grep RUNPATH | sed 's/.*\[\(.*\)\]/\1/' || true)"
say "  interp    ${INTERP:-none}"
say "  rpath     ${RPATH:-none}"
say "  runpath   ${RUNPATH:-none}"
UNRES="$(ldd "$OUT" 2>/dev/null | grep -c 'not found' || true)"
YOCTO="$(ldd "$OUT" 2>/dev/null | grep -c '/yocto' || true)"
say "  unresolved deps      ${UNRES:-0}"
say "  deps resolved from /yocto  ${YOCTO:-0}"
[ "${UNRES:-0}" -eq 0 ] || { echo "  REFUSING: unresolved dependencies" >&2; exit 1; }
[ "${YOCTO:-0}" -eq 0 ] || { echo "  REFUSING: a dependency resolves from /yocto" >&2; exit 1; }
case "$INTERP" in *yocto*) echo "  REFUSING: ELF interpreter under /yocto" >&2; exit 1;; esac
if strings -a "$OUT" 2>/dev/null | grep -q '/yocto'; then
    say "  NOTE: the binary contains a /yocto string (build-time path). Not a runtime dep,"
    say "        but recorded below so it is visible."
    HAS_STR=true
else
    HAS_STR=false
fi

# ---------------------------------------------------------------- build record
#
# ## This MERGES. It used to overwrite, and overwriting was the second half of the bug.
#
# The old version was a `cat > "$RECORD"` heredoc that rewrote the whole file. Every field the
# 2026-08-29 reconciliation added -- `deployed_by_unit`, `superseded_artifact`, `promoted_on`,
# `promotion_evidence`, `source_reproducible`, `verified_on` -- would have been destroyed by
# the next build. `deployed_by_unit` is the field that carries the unit cross-check, so the
# builder would have removed the one mechanism capable of reporting what it had just done.
#
# The split is the same one `ops/manifests/regenerate.sh` is built on, and for the same
# reason: this script writes ONLY what it uniquely knows -- which toolchain compiled this, on
# which host triple, whether the lock file was honoured, and when -- and then hands off to the
# generator for everything derivable from the bytes. Nothing here can invent a claim about
# provenance or reproducibility, because nothing here writes those fields.
say "recording the build"
python3 - "$RECORD" "$(rustc --version)" "$(cargo --version)" "$HOST_TRIPLE" \
         "$( [ -n "$LOCKED" ] && echo true || echo false )" "$HAS_STR" \
         "${UNRES:-0}" "${YOCTO:-0}" <<'PY'
import json, pathlib, subprocess, sys

record = pathlib.Path(sys.argv[1])
m = json.loads(record.read_text())

# Provenance only. The byte-facts -- size, sha256, st_nlink, elf_interpreter, rpath, runpath,
# build_id -- are deliberately absent from this dict and are filled in by regenerate.sh.
m.update({
    "rustc": sys.argv[2],
    "cargo": sys.argv[3],
    "host_triple": sys.argv[4],
    "locked": sys.argv[5] == "true",
    "contains_yocto_string": sys.argv[6] == "true",
    "unresolved_deps": int(sys.argv[7]),
    "deps_from_yocto": int(sys.argv[8]),
    "built_on": subprocess.run(["date", "-Is"], capture_output=True, text=True).stdout.strip(),
})
record.write_text(json.dumps(m, indent=2) + "\n")
print(f"  provenance merged into {record.name}; descriptive fields preserved")
PY

# The byte-facts, from the generator that owns them. `--check` afterwards is not belt-and-
# braces: it is what proves the record now agrees with the binary AND that the unit launches
# the artifact just recorded. A build that leaves those disagreeing should not report OK.
"$ROOT/ops/manifests/regenerate.sh" gateway-build.json || {
    echo "  the build record could not be regenerated" >&2; exit 1; }
if ! "$ROOT/ops/manifests/regenerate.sh" --check gateway-build.json; then
    echo >&2
    echo "  The build succeeded but the record does not agree with the deployed runtime." >&2
    echo "  Most likely the new binary is built and the unit is still running the old one," >&2
    echo "  which is expected until ops/install-runtime.sh restarts it. Nothing was installed." >&2
    exit 1
fi
say "build record: $RECORD"
say "OK"
