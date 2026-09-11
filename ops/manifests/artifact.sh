# Read an artifact manifest from shell. Source this; it defines functions and runs nothing.
#
#   . ops/manifests/artifact.sh
#   artifact_load llm-engine.json || <your policy here>
#   echo "$ART_ABS $ART_SERVER_SHA"
#   artifact_verify                       # hashes the disk, compares, prints the reason
#
# ## Why a helper and not four copies of a hash
#
# Four scripts need to know which artifact is the right one: `ops/deploy/install-runtime.sh` before
# it installs, `ops/deploy/verify-runtime.sh` after, `scripts/setup.sh` when it reports whether this
# machine can serve, and `apps/test_governor_paths.py` for the path the governor evicts. The
# obvious way to do that is to paste the sha256 into each -- and then there are four copies of
# one fact and no way to tell which is stale. `gateway-build.json` sat three days describing a
# binary that was not the one running, and nothing noticed, because nothing read it.
#
# So the manifest is the single source of truth and this is the only reader. No consumer
# contains a hash.
#
# ## One process per manifest
#
# `ops/deploy/verify-runtime.sh` had no python3 dependency before this, and a helper that spawned an
# interpreter per field would add a dozen. `artifact_fields` emits every field a caller could
# want as one block of `shlex.quote`d assignments from a single `python3`, and `artifact_load`
# eval's it. Hashing is a second, separate call because it is the expensive half and most
# callers do not want it -- `scripts/setup.sh` must not read a 4.6 GB GGUF to tell you node is
# missing.
#
# ## It has no policy, deliberately
#
# Every function returns a status and prints its reason to stdout; none of them exit. What a
# missing artifact MEANS differs by caller -- the verifier must fail loudly, the installer must
# refuse, and setup is an advisory that should say "not built yet" and carry on. Baking one of
# those three in would make the other two wrong.

# The repository root, derived from this file's own location -- not from the caller's, which
# may be `scripts/` or `ops/` or a test.
_ART_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ART_ROOT="$(cd "$_ART_HERE/../.." && pwd)"
ART_DIR="$_ART_HERE"

# artifact_fields <manifest.json> -- print shell assignments, or a reason on failure.
artifact_fields() {
    python3 - "$ART_DIR" "$ART_ROOT" "${1:-}" <<'PY'
import json, pathlib, shlex, sys

mdir, root, name = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
if not name:
    print("artifact_fields: no manifest named", file=sys.stderr); sys.exit(2)
path = mdir / name
if not path.exists():
    print(f"artifact_fields: {path} does not exist", file=sys.stderr); sys.exit(2)
try:
    m = json.loads(path.read_text())
except Exception as exc:
    print(f"artifact_fields: {name} is not readable JSON: {exc}", file=sys.stderr); sys.exit(2)

out = {}


def put(key, value):
    out[key] = "" if value is None else str(value)


rel = m.get("relative_path")
if not rel:
    print(f"artifact_fields: {name} has no relative_path", file=sys.stderr); sys.exit(2)

put("ART_MANIFEST", name)
put("ART_REL", rel)
put("ART_ABS", root / rel)
put("ART_IS_DIR", "1" if m.get("path_is_directory") else "0")
put("ART_SHA", m.get("sha256", ""))
put("ART_SIZE", m.get("size_bytes", m.get("total_size_bytes", "")))
put("ART_UNIT", m.get("deployed_by_unit", ""))
put("ART_ROLE", m.get("artifact_role", ""))
put("ART_REPRODUCIBLE", m.get("source_reproducible", ""))

# A tree manifest names the individual binaries inside it. `server` is the one the API
# spawns; `cli` is the one that was deliberately NOT promoted with it and is retained
# byte-for-byte -- see the skew record. Both are exposed so a caller can check either.
for role in ("server", "cli"):
    sub = m.get(role) or {}
    pre = f"ART_{role.upper()}"
    put(f"{pre}_REL", sub.get("relative_path", ""))
    put(f"{pre}_ABS", root / sub["relative_path"] if sub.get("relative_path") else "")
    put(f"{pre}_SHA", sub.get("sha256", ""))

# Custody: where a copy of this artifact lives when the working tree does not have it. The
# restore command is recorded in the manifest rather than composed here, so a caller that
# prints it is quoting the manifest and not inventing a procedure.
cust = m.get("custody") or {}
put("ART_BUNDLE", root / cust["bundle"] if cust.get("bundle") else "")
put("ART_BUNDLE_SHA", cust.get("bundle_sha256", ""))
put("ART_RESTORE", cust.get("restore", ""))
put("ART_EXTRACT_INTO", cust.get("extract_into", ""))

# Distribution is TRANSPORT. `ART_BUNDLE_SHA` above stays the acceptance criterion, and
# `artifact_fetch` checks the downloaded bytes against it rather than against anything the
# provider says. No credential is ever read from here: retrieval is anonymous by design.
dist = cust.get("distribution") or {}
put("ART_DIST_PROVIDER", dist.get("provider", ""))
put("ART_DIST_URL", dist.get("url", ""))
put("ART_DIST_TAG", dist.get("release_tag", ""))
put("ART_DIST_ASSET", dist.get("asset_name", ""))

for k, v in out.items():
    print(f"{k}={shlex.quote(v)}")
PY
}

# Every field `artifact_fields` sets. Named explicitly so `artifact_load` can clear them; a
# `compgen -v ART_` sweep would also take ART_ROOT and ART_DIR, which are this file's own.
_ART_FIELDS="ART_MANIFEST ART_REL ART_ABS ART_IS_DIR ART_SHA ART_SIZE ART_UNIT ART_ROLE
             ART_REPRODUCIBLE ART_SERVER_REL ART_SERVER_ABS ART_SERVER_SHA ART_CLI_REL
             ART_CLI_ABS ART_CLI_SHA ART_BUNDLE ART_BUNDLE_SHA ART_RESTORE
             ART_DIST_PROVIDER ART_DIST_URL ART_DIST_TAG ART_DIST_ASSET ART_EXTRACT_INTO"

# artifact_load <manifest.json> -- set ART_* in the CALLER's shell. Returns non-zero and
# leaves every field UNSET if the manifest cannot be read.
#
# The assignments are captured first and eval'd only on success. Piping python3 straight into
# eval would run whatever it managed to print before it failed, and a half-loaded manifest is
# worse than an unloaded one: the caller would see a plausible ART_ABS and no hash, and check
# the pathname while believing it had checked the artifact. Which is the bug this whole file
# exists to remove.
#
# The same argument is why a FAILED load clears the fields rather than leaving them alone.
# Callers load several manifests in sequence, so an untouched ART_ABS is not empty -- it holds
# the PREVIOUS artifact's path. A caller that then checks `[ -f "$ART_ABS" ]` would report on
# the wrong binary and pass, which is a stale-identity bug of exactly the kind these manifests
# were written to end.
artifact_load() {
    local fields status f
    fields="$(artifact_fields "${1:-}")"; status=$?
    if [ "$status" -ne 0 ]; then
        for f in $_ART_FIELDS; do unset "$f"; done
        return "$status"
    fi
    eval "$fields"
}

# artifact_verify -- hash what is on disk and compare it with the loaded manifest.
#
#   0  matches
#   1  present but WRONG -- the reason is printed
#   2  absent
#
# For a tree artifact the whole tree is compared entry by entry, so a swapped library counts
# as a mismatch and not only a swapped binary. That matters here: the promoted engine is nine
# shared objects and a launcher, and replacing one `.so` changes what runs without touching
# the file whose name is on the unit.
artifact_verify() {
    [ -n "${ART_MANIFEST:-}" ] || { echo "artifact_verify: nothing loaded"; return 1; }
    python3 - "$ART_DIR" "$ART_ROOT" "$ART_MANIFEST" <<'PY'
import hashlib, json, os, pathlib, sys

mdir, root, name = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
m = json.loads((mdir / name).read_text())
target = root / m["relative_path"]
if not target.exists():
    print(f"absent: {m['relative_path']}")
    sys.exit(2)


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


bad = []
if m.get("path_is_directory"):
    recorded = {e["name"]: e for e in m.get("tree", [])}
    on_disk = {}
    for f in sorted(target.iterdir(), key=lambda x: x.name):
        if f.is_symlink():
            on_disk[f.name] = {"name": f.name, "type": "symlink", "target": os.readlink(f)}
        else:
            on_disk[f.name] = {"name": f.name, "type": "file",
                               "size_bytes": f.stat().st_size, "sha256": sha(f)}
    for n in sorted(set(recorded) | set(on_disk)):
        if n not in on_disk:
            bad.append(f"missing from disk: {n}")
        elif n not in recorded:
            bad.append(f"not in the manifest: {n}")
        elif recorded[n] != on_disk[n]:
            was = recorded[n].get("sha256", recorded[n].get("target", "?"))
            now = on_disk[n].get("sha256", on_disk[n].get("target", "?"))
            bad.append(f"{n}: manifest {str(was)[:16]} disk {str(now)[:16]}")
else:
    got = sha(target)
    if got != m.get("sha256"):
        bad.append(f"{target.name}: manifest {str(m.get('sha256'))[:16]} disk {got[:16]}")

if bad:
    for b in bad[:6]:
        print(b)
    if len(bad) > 6:
        print(f"... and {len(bad) - 6} more")
    sys.exit(1)
print(f"matches the manifest ({m['relative_path']})")
PY
}

# artifact_fetch <destination-file> -- download the bundle named by the loaded manifest and
# verify it against the manifest's recorded hash. Call artifact_load first.
#
#   0  downloaded and the bytes match
#   1  downloaded and the bytes are WRONG, or the download failed
#   2  this manifest records no distribution reference
#
# ## The direction of the check is the whole design
#
# The hash compared against is `custody.bundle_sha256` from the manifest -- a file in git --
# and never anything the provider reports. GitHub is custody and transport; it does not get to
# say what the right binary is. Reversed, this would be "download whatever currently has this
# name and trust it", which is the failure the manifests exist to prevent.
#
# It is anonymous on purpose. A private release would work and would need a credential
# provisioned onto the rebuilt machine, which moves half of disaster recovery into a second
# custody problem. `--no-netrc` and the unset tokens are not belt-and-braces: they are what
# makes a passing run EVIDENCE that a machine with no account can do this, rather than proof
# that this machine's keyring works.
artifact_fetch() {
    local dest="${1:?usage: artifact_fetch <destination-file>}" got
    [ -n "${ART_MANIFEST:-}" ] || { echo "artifact_fetch: nothing loaded"; return 1; }
    if [ -z "${ART_DIST_URL:-}" ]; then
        echo "artifact_fetch: $ART_MANIFEST records no custody.distribution.url"
        return 2
    fi
    [ -n "${ART_BUNDLE_SHA:-}" ] || {
        echo "artifact_fetch: refusing to download with no recorded hash to check it against"
        return 1; }

    echo "  fetching $ART_DIST_ASSET from $ART_DIST_PROVIDER ($ART_DIST_TAG)"
    if ! env -u GH_TOKEN -u GITHUB_TOKEN -u GH_ENTERPRISE_TOKEN          curl -fsSL --no-netrc -o "$dest" "$ART_DIST_URL"; then
        echo "  download failed: $ART_DIST_URL"
        return 1
    fi
    got="$(sha256sum "$dest" | cut -d" " -f1)"
    if [ "$got" != "$ART_BUNDLE_SHA" ]; then
        echo "  REJECTED: the downloaded bytes are not the artifact this manifest names"
        echo "    manifest $ART_BUNDLE_SHA"
        echo "    download $got"
        return 1
    fi
    echo "  verified against the manifest: $got"
}

# artifact_restore <bundle-file> -- extract a fetched bundle into the tree the manifest names.
#
# This exists because `custody.restore` could not be used by the machine it was written for.
# It reads `tar -C engines/... -xzf releases/<bundle>`, and a rebuilt host has no `releases/`:
# it fetches to wherever it fetched to. So the recorded command only worked where the artifact
# was already present -- the one case needing no restore at all. Caught by reconstructing from
# a fresh clone, which is the only test that could have caught it; every earlier check ran on
# a machine that happened to have the file.
#
# The destination comes from `custody.extract_into` and the source is the caller's, so the two
# are independent, which is what makes this usable from a download directory.
artifact_restore() {
    local bundle="${1:?usage: artifact_restore <bundle-file>}" dest
    [ -n "${ART_MANIFEST:-}" ] || { echo "artifact_restore: nothing loaded"; return 1; }
    [ -f "$bundle" ] || { echo "artifact_restore: no such bundle: $bundle"; return 1; }
    [ -n "${ART_EXTRACT_INTO:-}" ] || {
        echo "artifact_restore: $ART_MANIFEST records no custody.extract_into"; return 2; }
    dest="$ART_ROOT/$ART_EXTRACT_INTO"
    mkdir -p "$dest" || return 1
    tar -C "$dest" -xzf "$bundle" || { echo "artifact_restore: extraction failed"; return 1; }
    echo "  restored into $ART_EXTRACT_INTO"
}
