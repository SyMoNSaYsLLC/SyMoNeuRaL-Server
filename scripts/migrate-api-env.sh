#!/usr/bin/env bash
# Split /etc/symoneural/api.env into two security domains, values UNCHANGED.
#
#   sudo ./scripts/migrate-api-env.sh plan      # classify every key, write nothing
#   sudo ./scripts/migrate-api-env.sh migrate   # create surfaces.env + accounts.env
#   sudo ./scripts/migrate-api-env.sh verify    # prove the split is value-identical
#   sudo ./scripts/migrate-api-env.sh retire    # tombstone api.env  (LAST, after rotation)
#
# MIGRATION AND ROTATION ARE SEPARATE OPERATIONS, and the order matters. This script moves
# values without changing one byte of them, so that if the API fails to start afterwards the
# cause is unambiguously the plumbing and not the secret. Rotation happens later, through
# scripts/accounts-runtime.sh, against a runtime already proven to work with the values it had.
# Doing both at once would leave two candidate causes for a failed boot and no way to separate
# them without printing a secret.
#
# FAILS CLOSED ON AN UNKNOWN KEY. A key with no declared destination aborts the migration
# rather than landing in a default domain. Defaulting is how a credential ends up in the file
# a feature-switch script is allowed to print -- which is the specific failure this split
# exists to make impossible.
set -euo pipefail

PROG="$(basename "$0")"
ETC=/etc/symoneural
LEGACY="$ETC/api.env"
SURFACES="$ETC/surfaces.env"
ACCOUNTS="$ETC/accounts.env"

die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "must run as root: sudo $0 ${1:-}"; }

# ---------------------------------------------------------------- the classification
# EXPLICIT, exhaustive, and checked. Every key the live service was measured to carry on
# 2026-09-04 appears here. Anything else stops the migration.
#
# The rule is domain OWNERSHIP, not sensitivity: SYM_*_TOKEN values are secrets too, but they
# are SURFACE secrets and enable-surfaces.sh is their legitimate owner. What must not happen
# is the session signer sitting in a file that script may rewrite or display.
domain_of() {
  case "$1" in
    SYMONEURAL_SESSION_SECRET|SYMONEURAL_ACCOUNTS_ENABLED)      echo accounts ;;
    SYM_CODER_ENABLED|SYM_CODER_TOKEN)                          echo surfaces ;;
    SYM_PROJECT_ENABLED|SYM_PROJECT_TOKEN)                      echo surfaces ;;
    SYM_STUDIO_ENABLED|SYM_STUDIO_TOKEN)                        echo surfaces ;;
    SYMONEURAL_CODER_ENABLED|SYMONEURAL_CODER_TOKEN)            echo surfaces ;;
    SYMONEURAL_PROJECT_ENABLED|SYMONEURAL_PROJECT_TOKEN)        echo surfaces ;;
    SYMONEURAL_STUDIO_ENABLED|SYMONEURAL_STUDIO_TOKEN)          echo surfaces ;;
    SYMONEURAL_STUDIO_LOCAL_BYPASS|SYMONEURAL_CODER_ALLOW_REMOTE) echo surfaces ;;
    SYMONEURAL_DISPATCHOS_ENABLED|SYMONEURAL_CODERS_ENABLED)    echo surfaces ;;
    SYMONEURAL_ASIC_ENABLED|SYMONEURAL_ASIC_RIGS)               echo surfaces ;;
    SYMONEURAL_GATEWAY_ENABLED|SYMONEURAL_GATEWAY_NETWORK|SYMONEURAL_GATEWAY_CONTRACT) echo surfaces ;;
    SYMONEURAL_MINING_ENABLED|SYMONEURAL_MINER_CMD)             echo surfaces ;;
    # Transport, not a surface switch and not a credential. It has to live somewhere the API
    # reads, and surfaces.env is the file that is always present.
    SYMONEURAL_PORT)                                            echo surfaces ;;
    *)                                                          echo UNKNOWN ;;
  esac
}

_keys() { grep -vE '^\s*(#|$)' "$LEGACY" | cut -d= -f1; }

_preflight() {
  [ -f "$LEGACY" ] || die "$LEGACY does not exist"
  local dupes bad
  dupes="$(_keys | sort | uniq -d)"
  # systemd's EnvironmentFile takes the LAST duplicate. Migrating a file with duplicates would
  # silently pick a winner and the operator would never know which.
  [ -z "$dupes" ] || die "duplicate keys in $LEGACY: $(echo "$dupes" | tr '\n' ' ')"
  bad="$(grep -vE '^\s*(#|$)' "$LEGACY" | grep -cvE '^[A-Za-z_][A-Za-z0-9_]*=' || true)"
  [ "$bad" -eq 0 ] || die "$bad malformed line(s) in $LEGACY"
}

cmd_plan() {
  need_root plan; _preflight
  local unknown=0
  printf '%-34s %s\n' KEY DESTINATION
  while read -r k; do
    d="$(domain_of "$k")"
    [ "$d" = UNKNOWN ] && unknown=$((unknown+1))
    printf '%-34s %s\n' "$k" "$d"
  done < <(_keys)
  echo
  if [ "$unknown" -gt 0 ]; then
    printf '%s: %d key(s) have no declared destination. Add them to domain_of() before migrating.\n' "$PROG" "$unknown" >&2
    return 3
  fi
  printf 'all keys classified; safe to migrate\n'
}

cmd_migrate() {
  need_root migrate; _preflight
  cmd_plan >/dev/null || die "classification incomplete -- run '$0 plan'"
  install -d -m 0700 -o root -g root "$ETC"
  local ts st at; ts="$(date --iso-8601=seconds)"
  st="$(mktemp "$ETC/.surfaces.XXXXXX")"; at="$(mktemp "$ETC/.accounts.XXXXXX")"
  chmod 600 "$st" "$at"; chown root:root "$st" "$at"
  printf '# SyMoNeuRaL surface domain -- owned by scripts/enable-surfaces.sh\n# migrated from api.env %s\n' "$ts" > "$st"
  printf '# SyMoNeuRaL account/session domain -- owned by scripts/accounts-runtime.sh\n# migrated from api.env %s\n' "$ts" > "$at"
  # Copy the LINE, not a re-quoted value: anything that re-quotes risks changing a byte, and
  # a byte changed in the session signer is an outage that looks like a rotation nobody ran.
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    case "$(domain_of "${line%%=*}")" in
      accounts) printf '%s\n' "$line" >> "$at" ;;
      surfaces) printf '%s\n' "$line" >> "$st" ;;
      *) rm -f "$st" "$at"; die "unclassified key ${line%%=*} -- nothing written" ;;
    esac
  done < "$LEGACY"
  sync -f "$st" 2>/dev/null || true; sync -f "$at" 2>/dev/null || true
  mv -f "$st" "$SURFACES"; mv -f "$at" "$ACCOUNTS"
  chown root:root "$SURFACES" "$ACCOUNTS"; chmod 600 "$SURFACES" "$ACCOUNTS"
  printf 'wrote %s and %s (0600 root:root)\n' "$SURFACES" "$ACCOUNTS"
  cmd_verify
}

cmd_verify() {
  need_root verify
  [ -f "$SURFACES" ] && [ -f "$ACCOUNTS" ] || die "domain files missing; run migrate"
  for f in "$SURFACES" "$ACCOUNTS"; do
    [ "$(stat -c '%U:%G' "$f")" = root:root ] || die "$f owner is not root:root"
    [ "$(stat -c '%a' "$f")" = 600 ] || die "$f mode is not 600"
  done
  # SEMANTIC EQUALITY, proven by comparing sorted KEY=VALUE sets -- not by eyeballing two
  # files and not by printing anything. Any difference prints only the KEY that differs.
  local a b
  a="$(grep -vE '^\s*(#|$)' "$LEGACY" | sort)"
  b="$(cat "$SURFACES" "$ACCOUNTS" | grep -vE '^\s*(#|$)' | sort)"
  if [ "$a" = "$b" ]; then
    printf 'verify: split is value-identical to %s (%d keys)\n' "$LEGACY" "$(printf '%s\n' "$a" | wc -l)"
  else
    printf 'verify: DIFFERS. keys only in legacy: %s\n' \
      "$(comm -23 <(printf '%s\n' "$a" | cut -d= -f1) <(printf '%s\n' "$b" | cut -d= -f1) | tr '\n' ' ')" >&2
    printf 'verify: keys only in split:  %s\n' \
      "$(comm -13 <(printf '%s\n' "$a" | cut -d= -f1) <(printf '%s\n' "$b" | cut -d= -f1) | tr '\n' ' ')" >&2
    return 4
  fi
}

cmd_retire() {
  need_root retire
  cmd_verify >/dev/null || die "refusing to retire: the split does not verify"
  # Refuse while anything still loads it. Retiring a file systemd is reading turns the next
  # restart into an outage, and the unit edit is a separate, reviewable change.
  if grep -rqs 'api\.env' /etc/systemd/system/symoneural-*.service; then
    die "a systemd unit still references api.env -- update EnvironmentFile= first"
  fi
  local tomb="$ETC/api.env.retired-$(date +%Y%m%d)"
  mv -f "$LEGACY" "$tomb"; chown root:root "$tomb"; chmod 600 "$tomb"
  printf 'retired %s -> %s (0600, still contains the pre-rotation values)\n' "$LEGACY" "$tomb"
  printf 'Shred it only after the rotated secret is proven in production.\n'
}

case "${1:-}" in
  plan) cmd_plan ;; migrate) cmd_migrate ;; verify) cmd_verify ;; retire) cmd_retire ;;
  *) cat >&2 <<EOF
usage: sudo $PROG {plan|migrate|verify|retire}

  plan     classify every key in $LEGACY; writes nothing; exits 3 if any key is unclassified
  migrate  create $SURFACES and $ACCOUNTS with values copied unchanged, then verify
  verify   prove the two domain files are value-identical to the legacy file
  retire   tombstone the legacy file -- only after verify passes and no unit references it

Values are never printed by any subcommand.
EOF
     exit 2 ;;
esac
