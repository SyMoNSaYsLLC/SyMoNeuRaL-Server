#!/usr/bin/env bash
# Owner of the ACCOUNT/SESSION security domain: /etc/symoneural/accounts.env
#
#   sudo ./scripts/accounts-runtime.sh status
#   sudo ./scripts/accounts-runtime.sh validate
#   sudo ./scripts/accounts-runtime.sh fingerprint
#   sudo ./scripts/accounts-runtime.sh rotate-session-secret
#
# WHY THIS EXISTS AS A SEPARATE SCRIPT. `scripts/enable-surfaces.sh` owns the SURFACE domain
# -- which surfaces are switched on and their per-surface tokens. It has no business holding
# the session signer, and the session signer has no business being edited by a script whose
# job is flipping feature switches. One automation per security domain, so a bug in the
# surface switchboard cannot reach the credential that signs every user's session.
#
# That separation is not theoretical. `--show` in the surface script printed every value whose
# name did not contain TOKEN, and the session signer -- which lived in the same file -- went
# out in the clear. Splitting the domains removes the signer from that script's reach entirely.
#
# THE SECRET NEVER LEAVES THIS FILE IN THE CLEAR. It is never printed, never accepted on argv
# (where `ps` would show it to every local user), never written to a temp file outside 0600,
# and never echoed by any subcommand. `fingerprint` exists precisely so a human can compare
# "is the running secret the one I installed" without ever seeing either.
set -euo pipefail

PROG="$(basename "$0")"
ETC=/etc/symoneural
ENV_FILE="$ETC/accounts.env"
KEY=SYMONEURAL_SESSION_SECRET
#: backend/apps/accounts._secret() refuses anything shorter. Kept in sync deliberately by
#: `apps/test_accounts_runtime.py`, which reads MIN_SECRET_CHARS out of the module rather than
#: repeating the number -- a constant duplicated in two files is a constant that will drift.
MIN_CHARS=32

die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "must run as root: sudo $0 $*"; }

# Read one key without exposing the file. Never echoes the value to a caller.
_get() { [ -f "$ENV_FILE" ] || return 1; sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

# A FINGERPRINT, not the secret: sha256 of the value, truncated. It is one-way and it is
# truncated, so it identifies a secret across two machines or across a rotation without being
# usable as one. Everything a human needs to answer "did it change" and nothing more.
_fingerprint() { printf '%s' "$1" | sha256sum | cut -c1-12; }

cmd_status() {
  need_root status
  printf 'env file : %s\n' "$ENV_FILE"
  if [ ! -f "$ENV_FILE" ]; then
    printf '           (absent -- accounts domain not migrated yet)\n'; return 0
  fi
  printf 'owner    : %s  mode %s\n' "$(stat -c '%U:%G' "$ENV_FILE")" "$(stat -c '%a' "$ENV_FILE")"
  # Names and shapes only. Same allow-list discipline as enable-surfaces.sh: anything not
  # explicitly known to be non-secret reports a length, never a value.
  while IFS='=' read -r k v; do
    case "$k" in
      ''|'#'*) continue ;;
      *_ENABLED) printf '  %-30s = %s\n' "$k" "$v" ;;
      *)         printf '  %-30s = <set, %d chars>\n' "$k" "${#v}" ;;
    esac
  done < "$ENV_FILE"
}

cmd_validate() {
  need_root validate
  [ -f "$ENV_FILE" ] || die "$ENV_FILE does not exist"
  local owner mode dupes
  owner="$(stat -c '%U:%G' "$ENV_FILE")"; mode="$(stat -c '%a' "$ENV_FILE")"
  [ "$owner" = "root:root" ] || die "owner is $owner, expected root:root"
  [ "$mode" = "600" ] || die "mode is $mode, expected 600"
  # A duplicate key is not a style problem: systemd's EnvironmentFile takes the LAST one, so a
  # stale duplicate above a good value silently wins or loses depending on order. Refuse.
  dupes="$(grep -vE '^\s*(#|$)' "$ENV_FILE" | cut -d= -f1 | sort | uniq -d)"
  [ -z "$dupes" ] || die "duplicate keys: $(echo "$dupes" | tr '\n' ' ')"
  grep -vE '^\s*(#|$)' "$ENV_FILE" | grep -qvE '^[A-Za-z_][A-Za-z0-9_]*=' && die "malformed line present" || true
  local secret; secret="$(_get "$KEY" || true)"
  [ -n "$secret" ] || die "$KEY is absent"
  [ "${#secret}" -ge "$MIN_CHARS" ] || die "$KEY is shorter than $MIN_CHARS characters"
  printf 'ok: %s validates (owner root:root, mode 0600, %s present and long enough)\n' "$ENV_FILE" "$KEY"
}

cmd_fingerprint() {
  need_root fingerprint
  local secret; secret="$(_get "$KEY" || true)"
  [ -n "$secret" ] || die "$KEY is absent from $ENV_FILE"
  printf '%s file    %s  (len %d)\n' "$KEY" "$(_fingerprint "$secret")" "${#secret}"
  # The RUNNING value can differ from the file when the service has not been restarted since
  # an edit. That divergence is the single most useful thing this command can report, and it
  # is invisible from either side alone.
  local pid running
  pid="$(systemctl show symoneural-api -p MainPID --value 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ "$pid" != "0" ] && [ -r "/proc/$pid/environ" ]; then
    running="$(tr '\0' '\n' < "/proc/$pid/environ" | sed -n "s/^$KEY=//p" | tail -1)"
    if [ -n "$running" ]; then
      printf '%s running %s  (len %d)\n' "$KEY" "$(_fingerprint "$running")" "${#running}"
      [ "$running" = "$secret" ] \
        && printf 'MATCH: the running service is using the value in the file\n' \
        || printf 'DIVERGED: the service has not been restarted since the file changed\n'
    fi
  fi
}

cmd_rotate() {
  need_root rotate-session-secret
  [ -f "$ENV_FILE" ] || die "$ENV_FILE does not exist; migrate first"
  cmd_validate >/dev/null
  local old new tmp; old="$(_get "$KEY")"
  # Generated HERE, inside the privileged operation, never passed in. A secret supplied on the
  # command line is visible in `ps` to every local user for the life of the call, which is the
  # same class of mistake as printing it.
  new="$(openssl rand -hex 32)"
  [ "${#new}" -ge "$MIN_CHARS" ] || die "generated secret too short -- openssl misbehaved"
  [ "$new" != "$old" ] || die "generated secret equals the current one -- refusing"

  # Atomic: write a 0600 temp file in the same directory, fsync it, then rename. A partial
  # write here would leave the API unable to start, and `EnvironmentFile=` failures at boot
  # are the kind that look like a hardware problem at 3am.
  tmp="$(mktemp "$ETC/.accounts.env.XXXXXX")"
  chmod 600 "$tmp"; chown root:root "$tmp"
  # Preserve every unrelated key exactly, replacing only this one.
  awk -v k="$KEY" -v v="$new" -F= '
    /^[[:space:]]*(#|$)/ { print; next }
    $1 == k { print k "=" v; found=1; next }
    { print }
    END { if (!found) print k "=" v }
  ' "$ENV_FILE" > "$tmp"
  sync -f "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$ENV_FILE"
  chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"

  printf 'rotated %s in %s\n' "$KEY" "$ENV_FILE"
  printf '  old fingerprint %s\n' "$(_fingerprint "$old")"
  printf '  new fingerprint %s\n' "$(_fingerprint "$new")"
  printf '\nNOT YET IN EFFECT. The API re-reads this file only on restart:\n'
  printf '    sudo -n /usr/local/sbin/symoneural-root restart-api\n'
  printf 'Then confirm with:  sudo %s fingerprint   (expect MATCH on the new value)\n' "$0"
  printf '\nEvery session issued under the old secret stops validating at that restart --\n'
  printf 'that is the design, not a side effect: backend/apps/accounts stores\n'
  printf 'hmac(secret, token) per session row, so rotation IS invalidation.\n'
}

case "${1:-}" in
  status)                cmd_status ;;
  validate)              cmd_validate ;;
  fingerprint)           cmd_fingerprint ;;
  rotate-session-secret) cmd_rotate ;;
  *) cat >&2 <<EOF
usage: sudo $PROG <command>

  status                 names and value SHAPES for the accounts domain; no values
  validate               ownership, mode, duplicate/malformed keys, secret present and long enough
  fingerprint            truncated sha256 of the file value and the RUNNING value; reports divergence
  rotate-session-secret  generate + install a new signer atomically; never prints it

Owns ONLY $ENV_FILE. Surface configuration belongs to scripts/enable-surfaces.sh.
EOF
     exit 2 ;;
esac
