# require.sh -- preconditions, stated once, refused loudly.
#
# Source it:  . "$ROOT/scripts/lib/say.sh"; . "$ROOT/scripts/lib/require.sh"
#
# Eight scripts tested `id -u` and eight tested `command -v`, each with its own message.
# A refusal is the thing an operator reads most often, so it is worth having one shape:
# what is missing, and what to do about it.

need_root() {
  [ "$(id -u)" -eq 0 ] || die "needs root: sudo $0 $*"
}

# Not for the repository's own code -- for the system binaries a script shells out to.
# Names the package where the name differs from the command, because "install curl" is
# obvious and "install libimage-exiftool-perl" is not.
need_cmd() {
  local cmd="$1" pkg="${2:-$1}"
  command -v -- "$cmd" >/dev/null 2>&1 || die "$cmd not found -- apt install $pkg"
}

need_file() { [ -f "$1" ] || die "missing file: $1${2:+ -- $2}"; }
need_dir()  { [ -d "$1" ] || die "missing directory: $1${2:+ -- $2}"; }

# Typed, not y/n. Every caller of this is about to do something that costs money, evicts a
# surface, or overwrites weights -- a single keystroke is too cheap for that, and a default
# answer is how a --dry-run habit turns into an accident. Refuses outright when there is no
# terminal, because an unattended run must never be able to answer its own question.
confirm() {
  local prompt="$1" want="${2:-yes}" got
  [ -t 0 ] || die "refusing: '$prompt' needs a terminal to confirm on"
  printf '%s\n  type %s to continue: ' "$prompt" "$want"
  read -r got
  [ "$got" = "$want" ] || die "not confirmed -- nothing was changed"
}

# DRY_RUN=1 makes every run() a description. Two scripts grew this separately and named the
# variable the same way, which is the signal it belongs here.
run() {
  if [ "${DRY_RUN:-0}" = "1" ]; then dim "would run: $*"; return 0; fi
  "$@"
}
