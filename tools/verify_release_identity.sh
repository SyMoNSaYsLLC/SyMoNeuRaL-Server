#!/usr/bin/env bash
# Verify that an export archive's stated release identity is cryptographically bound.
#
# WHY THIS IS A SEPARATE TOOL AND NOT PART OF THE EXPORTER
#
# The exporter must remain runnable with no signing key present. Its refusal paths -- the
# allow-list, the protected classes, the P1 signing-material checks, the P2 identity and
# drift checks -- are security controls that have to work today, on a box where zero keys
# exist. Folding tag verification into it would make every one of those refusals depend on
# signing infrastructure being installed, which inverts the dependency: a missing key would
# start disabling protections rather than blocking a release. D-11 sec 22.4 item 6 records
# the same separation -- "a separate signer invoked after the exporter, never inside it".
#
# So: the exporter proves the archive is honestly LABELLED. This tool proves the label is
# BOUND to the D-11 release authority. Different questions, different failure modes,
# different prerequisites.
#
# THE TWO MANDATORY CONDITIONS (D-11 P2-c)
#
#   signed release tag
#         |  tag signature verifies against the authorized release key
#         v
#   tag resolves to a commit SHA
#         |
#         v
#   that commit SHA == the archive manifest's source-sha
#
# BOTH must hold. They are checked independently and both are reported, because they fail
# for different reasons: a signature failure means the tag is not from the release
# authority; a SHA mismatch means the tag is authentic but points somewhere else -- an
# authentic signature over the wrong release. Either one fails the release.
#
# NO KEY EXISTS YET. That is why the verifier is injected rather than hardcoded:
# SYMONEURAL_TAG_VERIFY_CMD receives the tag name and must exit 0 only if the signature verifies
# against the authorized release key. It defaults to `git verify-tag`, which is what the
# future key ceremony will supply an actual key for. Nothing here needs redesigning when
# that key arrives -- only the default becomes usable.
#
# This tool does not sign, publish, distribute, or authorize anything. External release
# remains gated on a separate authorization.
#
#   verify_release_identity.sh --tag <name> --source-sha <sha> [--root <dir>]
#   verify_release_identity.sh --tag <name> --archive <archive.zip> [--root <dir>]
set -euo pipefail

PROG="$(basename "$0")"
die()  { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }
fail() { printf '%s: RELEASE IDENTITY UNVERIFIED -- %s\n' "$PROG" "$*" >&2; exit 3; }
info() { printf '%s: %s\n' "$PROG" "$*"; }

TAG="" SOURCE_SHA="" ARCHIVE="" ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tag)        TAG="${2:-}";        shift 2 ;;
    --source-sha) SOURCE_SHA="${2:-}"; shift 2 ;;
    --archive)    ARCHIVE="${2:-}";    shift 2 ;;
    --root)       ROOT="${2:-}";       shift 2 ;;
    -h|--help)    sed -n '2,46p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$TAG" ] || die "--tag is required"
[ -n "$ROOT" ] || ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$ROOT" ] || die "root not a directory: $ROOT"
ROOT="$(cd "$ROOT" && pwd)"

# The archive states its own identity. Reading it from the archive is the real workflow;
# --source-sha exists so the check can be run against a value obtained some other way.
if [ -z "$SOURCE_SHA" ]; then
  [ -n "$ARCHIVE" ] || die "one of --source-sha or --archive is required"
  [ -f "$ARCHIVE" ] || die "archive not found: $ARCHIVE"
  command -v unzip >/dev/null 2>&1 || die "unzip not available"
  SOURCE_SHA="$(unzip -p "$ARCHIVE" EXPORT-MANIFEST 2>/dev/null \
                | sed -n 's/^source-sha: *//p' | head -1)"
  [ -n "$SOURCE_SHA" ] || fail "archive has no source-sha in EXPORT-MANIFEST"
fi

# An unresolved identity cannot be bound to anything. P2-a makes the exporter incapable of
# emitting this, so reaching it means the archive predates P2 or was not built by the
# sanctioned exporter -- either way it is not releasable.
case "$SOURCE_SHA" in
  UNKNOWN|"") fail "stated source-sha is unresolved ('$SOURCE_SHA'); not releasable" ;;
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) : ;;
  *) fail "stated source-sha is not a commit SHA: '$SOURCE_SHA'" ;;
esac

git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 \
  || fail "$ROOT is not a git repository; cannot resolve the release tag"

# --- CONDITION 1: the tag signature must verify against the authorized release key -------
# Canonical spelling first, legacy second, default last -- the same order every other reader
# on this tree uses (backend/symoneuralenv.py owns the rename). The legacy name is still
# honoured rather than dropped: an operator's existing key-ceremony wrapper must not start
# silently falling back to plain `git verify-tag`, which would turn an unverifiable release
# into a passing one. That is the one failure mode this whole script exists to prevent, so
# the compatibility branch stays until the rename is finished everywhere.
VERIFY_CMD="${SYMONEURAL_TAG_VERIFY_CMD:-${SYM_TAG_VERIFY_CMD:-git -C $ROOT verify-tag}}"
set +e
# shellcheck disable=SC2086
$VERIFY_CMD "$TAG" >/dev/null 2>&1
verify_rc=$?
set -e
if [ "$verify_rc" -ne 0 ]; then
  fail "tag '$TAG' signature did not verify against the authorized release key (rc=$verify_rc)"
fi

# --- CONDITION 2: the tag's commit must equal the stated source-sha ----------------------
# Checked independently of condition 1. An authentic signature over a DIFFERENT commit is a
# real attack shape -- reuse a genuinely signed tag to bless an archive built elsewhere --
# so "the tag verified" is never allowed to imply "the tag points at this release".
TAG_COMMIT="$(git -C "$ROOT" rev-list -n 1 "$TAG" 2>/dev/null || true)"
[ -n "$TAG_COMMIT" ] || fail "tag '$TAG' does not resolve to a commit"

if [ "$TAG_COMMIT" != "$SOURCE_SHA" ]; then
  fail "tag '$TAG' commit $TAG_COMMIT != archive source-sha $SOURCE_SHA"
fi

info "tag '$TAG' signature verified against the authorized release key"
info "tag commit == archive source-sha: $SOURCE_SHA"
info "RELEASE IDENTITY VERIFIED -- this authorizes no distribution"
