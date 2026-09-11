# say.sh -- one voice for every script here.
#
# Source it:  . "$ROOT/scripts/lib/say.sh"
#
# Eight scripts defined say/dim/warn/die and five of them printed differently -- one plain,
# one bold with "== ", one cyan with "==> ", two with a two-space indent. The same operator
# reading three of them in a row could not tell which lines were headings.
#
# Colour is TTY-gated. These run under systemd, in CI and through `tee`, and an escape
# sequence in a journal entry is noise that survives forever. NO_COLOR is honoured because
# it is the one convention everybody agreed on.

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  AMBER=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'
else
  BOLD=''; DIM=''; RED=''; GREEN=''; AMBER=''; CYAN=''; OFF=''
fi

PROG="${PROG:-${0##*/}}"

head_() { printf '\n%s== %s%s\n'   "$BOLD"  "$*" "$OFF"; }   # a section
say()   { printf '%s\n'            "$*"; }                   # ordinary output
dim()   { printf '%s  %s%s\n'      "$DIM"   "$*" "$OFF"; }   # detail, indented
ok()    { printf '  %sok%s    %s\n' "$GREEN" "$OFF" "$*"; }
note()  { printf '  %snote%s  %s\n' "$AMBER" "$OFF" "$*"; }
bad()   { printf '  %sFAIL%s  %s\n' "$RED"   "$OFF" "$*"; }
step()  { printf '%s==>%s %s\n'    "$CYAN"  "$OFF" "$*"; }

# stderr, always, and the program name is on it -- an operator reading a journal needs to
# know which of nine scripts produced the line.
warn()  { printf '%s%s: %s%s\n'    "$AMBER" "$PROG" "$*" "$OFF" >&2; }
die()   { printf '%s%s: %s%s\n'    "$RED"   "$PROG" "$*" "$OFF" >&2; exit 1; }
