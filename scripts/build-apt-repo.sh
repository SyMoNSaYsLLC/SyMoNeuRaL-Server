#!/usr/bin/env bash
# Publish the built .deb into a local apt repository, so upgrading is
#
#     sudo apt update && sudo apt upgrade
#
# rather than `sudo scripts/deploy.sh --prune`.
#
#     ./scripts/build-apt-repo.sh [--repo DIR] [--build]
#
#       --build     build a fresh .deb from HEAD first (scripts/build-deb.sh)
#       --repo DIR  where the repository lives (default /home/google/symoneural-apt)
#
# NO ROOT NEEDED to create or refresh the repository. Root is needed exactly once, to tell
# apt the repository exists; this script prints that command rather than running it.
#
# WHY A FLAT REPOSITORY. This is a trivial `Packages`/`Release` pair in one directory --
# no `dists/`, no `pool/`, no suites. A distribution repository's structure exists to serve
# many architectures and releases over a mirror network; this serves one `all` package from
# a local path, and the flat format is the one apt supports for exactly that.
#
# ON SIGNING, PLAINLY. The sources line this prints carries `trusted=yes`, which tells apt
# to accept the repository without a signature. That is not "signing turned off for
# convenience" hand-waving -- it is a real reduction in what apt verifies, and the honest
# statement of what protects you instead is: the repository is a directory on this disk, and
# whoever can write to it can already write to /opt/symoneural directly. The signature would
# be verifying a path against the same filesystem that holds the key.
#
# That reasoning stops holding the moment the repository is served over a network to another
# host, which is what `--sign` is for: pass it and, if a secret key exists, the script writes
# a detached `InRelease` and prints the keyring install command instead. Without a key it says
# so and does not silently fall back.
set -euo pipefail

. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"

REPO="/home/google/symoneural-apt"
BUILD=0
SIGN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --build) BUILD=1; shift;;
    --sign) SIGN=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

command -v dpkg-scanpackages >/dev/null || {
  echo "dpkg-scanpackages not found -- it is in the 'dpkg-dev' package:" >&2
  echo "    sudo apt install dpkg-dev" >&2
  exit 1
}

mkdir -p "$REPO"

if [ "$BUILD" -eq 1 ]; then
  echo "building a fresh package from HEAD:"
  "$ROOT/scripts/build-deb.sh" -o "$REPO" | sed 's/^/  /'
  echo
fi

count="$(find "$REPO" -maxdepth 1 -name 'symoneural_*.deb' | wc -l)"
if [ "$count" -eq 0 ]; then
  echo "no symoneural_*.deb in $REPO" >&2
  echo "put one there, or re-run with --build" >&2
  exit 1
fi

# Every version is kept, not just the newest. apt picks the highest itself, and keeping the
# predecessors is what makes `sudo apt install symoneural=<older version>` a working
# rollback rather than a sentence in a document.
cd "$REPO"
dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null
gzip -9cn Packages > Packages.gz

# A Release file is not optional even for a flat repo: without it apt reports
# "Missing Release file" and skips the source entirely, which reads like the packages
# are simply absent. The checksum fields are what apt validates Packages against.
{
  echo "Origin: SyMoNeuRaL"
  echo "Label: SyMoNeuRaL local"
  echo "Suite: stable"
  echo "Codename: stable"
  echo "Architectures: all amd64 arm64"
  echo "Components: main"
  echo "Description: SyMoNeuRaL local AI stack -- local apt repository"
  echo "Date: $(date -Ru)"
  echo "MD5Sum:"
  for f in Packages Packages.gz; do
    printf ' %s %16d %s\n' "$(md5sum "$f" | cut -d' ' -f1)" "$(stat -c%s "$f")" "$f"
  done
  echo "SHA256:"
  for f in Packages Packages.gz; do
    printf ' %s %16d %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$(stat -c%s "$f")" "$f"
  done
} > Release

TRUST="[trusted=yes] "
KEYNOTE=""
if [ "$SIGN" -eq 1 ]; then
  if command -v gpg >/dev/null \
     && gpg --list-secret-keys --with-colons 2>/dev/null | grep -q '^sec'; then
    gpg --clearsign --output InRelease.new Release && mv InRelease.new InRelease
    gpg --armor --export > symoneural-archive-keyring.asc
    TRUST=""
    KEYNOTE="  sudo install -m 644 $REPO/symoneural-archive-keyring.asc \\
      /etc/apt/trusted.gpg.d/symoneural-archive-keyring.asc"
  else
    echo "--sign was asked for but this account has no gpg secret key." >&2
    echo "Not falling back to unsigned silently. Create one with 'gpg --quick-gen-key'" >&2
    echo "or drop --sign and accept trusted=yes, which is documented in this script." >&2
    exit 1
  fi
fi

newest="$(grep -h '^Version:' Packages | sed 's/^Version: //' | sort -V | tail -1)"

echo "repository  $REPO"
echo "packages    $count ($(du -sh "$REPO" | cut -f1))"
echo "newest      $newest"
echo
echo "Tell apt about it -- once per host, needs root:"
echo
if [ -n "$KEYNOTE" ]; then echo "$KEYNOTE"; fi
echo "  echo 'deb ${TRUST}file://$REPO ./' \\"
echo "      | sudo tee /etc/apt/sources.list.d/symoneural.list"
echo
echo "From then on, on this host and any other host with that file:"
echo
echo "  sudo apt update && sudo apt upgrade      # picks up every new build"
echo "  sudo apt install symoneural              # the first install"
echo
echo "On another machine, point the source at this directory over the network instead of"
echo "file:// -- and use --sign, because the argument for trusted=yes above does not"
echo "survive the repository being reachable from somewhere you do not control."
