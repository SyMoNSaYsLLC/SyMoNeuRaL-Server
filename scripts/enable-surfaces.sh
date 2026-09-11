#!/usr/bin/env bash
#
# Switch on the token-gated surfaces that ship OFF by default: Coder, Project, Studio, Asic,
# and the operator power switch this repo calls Rack. Optionally the TRON licensing Gateway,
# which needs two facts this script cannot invent, and DispatchOS, which issues no shared
# token at all -- its accounts are per-person scrypt hashes written by
# tools/lib/dispatchos_accounts.py, so this script only flips its switch.
#
#   sudo ./scripts/enable-surfaces.sh project rack
#   sudo ./scripts/enable-surfaces.sh coder studio                # local-only, see below
#   sudo ./scripts/enable-surfaces.sh asic --rigs 10.0.0.11,10.0.0.12
#   sudo ./scripts/enable-surfaces.sh gateway --network symoneural-test \
#          --contract TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
#   sudo ./scripts/enable-surfaces.sh dispatchos                  # switch only; see above
#   sudo ./scripts/enable-surfaces.sh coders                      # switch only; loopback-only
#   sudo ./scripts/enable-surfaces.sh --show                      # what is set, no secrets
#
# ## Why a drop-in and an env file rather than editing the unit
#
# The live unit is the TEMPLATED copy at /etc/systemd/system/symoneural-api.service, written
# by ops/deploy/install-service.sh with the repo root substituted in. Editing ops/units/symoneural-api.service
# changes nothing that is running, and editing the installed copy is undone the next time
# anybody re-runs the installer. A drop-in at .../symoneural-api.service.d/ survives both.
#
# Tokens do NOT go in `Environment=` lines. `systemctl show symoneural-api` prints those to
# any user on the box, which would put a shared secret in the output of an unprivileged
# command. They go in /etc/symoneural/api.env, root-owned and mode 0600, referenced by
# `EnvironmentFile=`. That file is outside the repo and can never be committed by accident.
#
# ## What this script will not do
#
# It will not enable remote access to anything. SYMONEURAL_CODER_ALLOW_REMOTE and
# SYMONEURAL_RACK_ALLOW_REMOTE are never written here, so both surfaces stay loopback-only, which
# is the shape their own documentation argues for: backend/coder/README.md is explicit
# that an agent which can develop the site is arbitrary code execution on the box that
# serves the public internet. Opening either one to the network is a deliberate act and
# should look like one -- add the line by hand, having decided to.
#
# It will not overwrite a token that already exists. Re-running is safe and idempotent: a
# surface already switched on keeps the token it has, so restarting does not invalidate a
# session or a saved credential somewhere else.
set -euo pipefail

ENV_FILE=/etc/symoneural/api.env
DROPIN_DIR=/etc/systemd/system/symoneural-api.service.d
DROPIN="$DROPIN_DIR/10-surfaces.conf"
UNIT=symoneural-api.service

die() { printf '%s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "This writes to /etc and restarts a service. Run it with sudo."

# ---------------------------------------------------------------- read what is already set

# `set -a` in a subshell, so a malformed line cannot leak into this script's own namespace.
get_var() {
  [ -f "$ENV_FILE" ] || { printf ''; return; }
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

show() {
  printf 'env file : %s\n' "$ENV_FILE"
  if [ ! -f "$ENV_FILE" ]; then
    printf '           (absent -- nothing enabled by this script)\n'
    return
  fi
  # ALLOW-LIST, and the comment this replaces claimed "values are never printed" while
  # printing every value whose name did not contain TOKEN. `SYMONEURAL_SESSION_SECRET` is in
  # this exact file and does not contain TOKEN, so `--show` printed the live session-signing
  # secret in full, under a comment promising it would not. Measured 2026-09-03: a 64-character
  # value reached two retained agent transcripts, one of them world-readable.
  #
  # A deny-list cannot fix this, only postpone it. It has to enumerate every way a future
  # variable might be named -- SECRET, PASSWORD, KEY, CREDENTIAL, PASSPHRASE, SIGNING, SALT --
  # and the one nobody thought of is exactly the one that leaks. The allow-list below inverts
  # the default: a name nobody has classified prints as `<set, N chars>` rather than in full,
  # so a variable added next month is safe before anyone edits this script. Same argument
  # ops/registry/EXPORTS.md makes for the exporter and `apps/coders.child_env` for provider
  # children: the two architectures give opposite answers for the unclassified name, and only
  # one of them fails closed.
  #
  # What is on the list is what an operator needs `--show` FOR: which surfaces are switched on,
  # which port, and the two non-secret gateway facts. Every entry is a flag, a port or a public
  # identifier -- nothing here is a credential, and nothing that becomes one may be added.
  while IFS='=' read -r k v; do
    case "$k" in
      ''|'#'*) continue ;;
      *_ENABLED|SYMONEURAL_PORT|*_NETWORK|*_CONTRACT|*_RIGS|*_BASE_URL|*_ALLOW_REMOTE)
        printf '  %-28s = %s\n' "$k" "$v" ;;
      *)
        # Length only. It answers "is it set, and does it look empty or truncated" -- the two
        # questions an operator actually has -- without putting the value in a scrollback and,
        # sooner or later, in a screenshot or a session transcript.
        printf '  %-28s = <set, %d chars>\n' "$k" "${#v}" ;;
    esac
  done < "$ENV_FILE"
}

# ---------------------------------------------------------------- arguments

WANT_CODER=0 WANT_PROJECT=0 WANT_RACK=0 WANT_GATEWAY=0 WANT_STUDIO=0 WANT_ASIC=0
WANT_DISPATCHOS=0 WANT_CODERS=0
GW_NETWORK="" GW_CONTRACT="" ASIC_RIGS=""

[ $# -gt 0 ] || die "Nothing asked for." \
  "Surfaces: coder coders project studio asic rack gateway dispatchos (or --show)."

while [ $# -gt 0 ]; do
  case "$1" in
    coder)   WANT_CODER=1 ;;
    project) WANT_PROJECT=1 ;;
    rack)    WANT_RACK=1 ;;
    gateway) WANT_GATEWAY=1 ;;
    studio)  WANT_STUDIO=1 ;;
    asic)    WANT_ASIC=1 ;;
    dispatchos) WANT_DISPATCHOS=1 ;;
    coders)  WANT_CODERS=1 ;;
    --network)  GW_NETWORK="${2:-}"; shift ;;
    --rigs)     ASIC_RIGS="${2:-}"; shift ;;
    --contract) GW_CONTRACT="${2:-}"; shift ;;
    --show)  show; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
  shift
done

# The two facts this script cannot invent. symoneural-live is real money and a contract
# address is not guessable, so a missing one is a hard stop rather than a default.
#
# These are the only three names accepted, and TRON's own (nile, shasta, mainnet) are not
# among them: backend/gateway/chain.py holds the one-way map and refuses anything outside
# it, so writing `nile` here would produce a surface that reads `offline` with a message
# listing these three. One vocabulary, so a value that looks configured cannot mean a chain
# nobody chose. The rack still prints TRON's name for the chain it is actually on.
if [ "$WANT_GATEWAY" -eq 1 ]; then
  case "$GW_NETWORK" in
    symoneural-live|symoneural-test|symoneural-test-old) ;;
    "") die "gateway needs --network symoneural-live|symoneural-test|symoneural-test-old." \
            "There is no sane default: symoneural-live is real money." ;;
    nile|shasta|mainnet)
        die "--network takes symoneural-live|symoneural-test|symoneural-test-old, not TRON's" \
            "own name for the chain. symoneural-test is the testnet you want." ;;
    *)  die "--network must be one of symoneural-live, symoneural-test," \
            "symoneural-test-old (got '$GW_NETWORK')." ;;
  esac
  [ -n "$GW_CONTRACT" ] || die "gateway needs --contract, the deployed licensing contract" \
                               "address (34 chars, begins with T)."
  case "$GW_CONTRACT" in
    T?????????????????????????????????) ;;
    *) die "--contract does not look like a TRON address:" \
           "expected 34 characters beginning with T." ;;
  esac
fi

# Unlike --network, --rigs is optional: `asic` with no addresses is a legitimate state and
# the rack says so in as many words ("no rigs configured"). But --rigs with no `asic` writes
# nothing at all, and a silently ignored argument is the same defect as a WANT_ flag that no
# write path reads -- so it stops here rather than looking like it worked.
if [ -n "$ASIC_RIGS" ] && [ "$WANT_ASIC" -eq 0 ]; then
  die "--rigs only means something with the asic surface. Add 'asic' to the arguments."
fi

# ---------------------------------------------------------------- write

install -d -m 0700 -o root -g root /etc/symoneural
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<'HEADER'
# SyMoNeuRaL API surface switches. Written by scripts/enable-surfaces.sh.
#
# Root-owned, mode 0600, and deliberately OUTSIDE the repo: these are shared secrets and
# there is no git remote today, but "not committed" should not depend on remembering.
# Read by symoneural-api.service via an EnvironmentFile= drop-in -- NOT by Environment=
# lines, which `systemctl show` would print to any user on the box.
HEADER
fi
chown root:root "$ENV_FILE"; chmod 0600 "$ENV_FILE"

# Set KEY=VALUE, but never clobber an existing non-empty value.
set_kv() {
  local key="$1" val="$2" existing
  existing="$(get_var "$key")"
  if [ -n "$existing" ]; then
    printf '  %-28s kept (already set)\n' "$key"
    return
  fi
  printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  case "$key" in
    *TOKEN*) printf '  %-28s generated\n' "$key" ;;
    *)       printf '  %-28s = %s\n' "$key" "$val" ;;
  esac
}

# secrets.token_urlsafe(32), exactly as backend/project/store.py instructs -- "generate
# it with secrets.token_urlsafe(32) and never by hand". The system interpreter, since that is
# the serving path's interpreter and no virtualenv is involved.
gen_token() { /usr/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }

printf 'Writing %s\n' "$ENV_FILE"
# Four surfaces, one shape: SYMONEURAL_<NAME>_ENABLED=1 plus a fresh token. This was four aligned
# one-liners; each of the three that existed already ran past this repo's 100-column limit and
# adding Studio would have made a fourth, so the shape is a loop over "want-flag NAME" pairs.
# Gateway is not in here because it takes two more values and cannot share the body.
for pair in "$WANT_CODER CODER" "$WANT_PROJECT PROJECT" "$WANT_RACK RACK" \
            "$WANT_STUDIO STUDIO" "$WANT_ASIC ASIC"; do
  want=${pair% *}
  name=${pair#* }
  [ "$want" -eq 1 ] || continue
  set_kv "SYMONEURAL_${name}_ENABLED" 1
  set_kv "SYMONEURAL_${name}_TOKEN" "$(gen_token)"
done
# Not a token, so it is printed rather than reported as "generated", and it goes in the same
# 0600 file anyway rather than an `Environment=` line -- backend/asicminer/README.md:65
# suggests a drop-in for it, which is fine for a rig address and wrong for the token beside it.
# One file, one place to look. Empty stays empty: `rigs()` at asicminer/__init__.py:80 treats
# unset and "" identically, so there is nothing to write when the operator gave no addresses.
# DispatchOS: ONE switch and NO token, which is why it cannot join the loop above.
#
# Every surface in that loop pairs an ENABLED flag with a generated bearer token because none
# of them has a login -- the token IS their authentication. DispatchOS has real accounts with
# scrypt password hashes (backend/dispatchos/store.py), so a shared bearer token beside
# them would be a second and weaker credential for the same data, and one that would have to
# be handed to a customer on top of the password he is already being given.
#
# It is also the reason this surface writes nothing secret here at all: there is no value in
# this file that unlocks it. The accounts are in the store, and the passwords are set by
# tools/lib/dispatchos_accounts.py, which writes them to a root-owned 0600 file rather than to a
# terminal -- a credential that has been displayed is spent (request ledger R-168).
# Like dispatchos, a switch and nothing else -- this surface mints no shared bearer token.
# It is reachable only from a loopback peer with no x-forwarded-* header (api.py
# `_require_local`), and unlike `coder` it has no ALLOW_REMOTE escape hatch, so there is no
# network path for a secret to defend. See backend/coders/__init__.py for that reasoning.
if [ "$WANT_CODERS" -eq 1 ]; then
  set_kv SYMONEURAL_CODERS_ENABLED 1
fi

if [ "$WANT_DISPATCHOS" -eq 1 ]; then
  set_kv SYMONEURAL_DISPATCHOS_ENABLED 1
fi

if [ "$WANT_ASIC" -eq 1 ] && [ -n "$ASIC_RIGS" ]; then
  set_kv SYMONEURAL_ASIC_RIGS "$ASIC_RIGS"
fi
if [ "$WANT_GATEWAY" -eq 1 ]; then
  set_kv SYMONEURAL_GATEWAY_ENABLED 1
  set_kv SYMONEURAL_GATEWAY_NETWORK "$GW_NETWORK"
  set_kv SYMONEURAL_GATEWAY_CONTRACT "$GW_CONTRACT"
fi

# ## The gated surfaces this script deliberately does not switch
#
# Eight env-gated surfaces have no arm here. Asic gained one above, because its rack row was in
# exactly the state Studio's was -- SubUnit `asicminer` (backend/server.py:1655) told an operator
# to "set SYMONEURAL_ASIC_ENABLED=1 ... and SYMONEURAL_ASIC_TOKEN" and nothing sanctioned would
# do it. News then joined the list -- it was always in this state and the test could not see
# it, because the test's regex looked for the `SYM_` prefix and news was the first surface
# named `SYMONEURAL_*` from the start. Discovery joined it on the day it landed, caught by the
# test below before its first commit rather than found later on a rack. Live joined it the
# same way and for a reason unlike any of the others -- it is the one surface that is already
# on. The eight are not oversights and each is a different reason, so they are named rather
# than left as a silence someone has to re-derive:
#
#   accounts   -- the key is not a token. `enabled()` (apps/accounts/__init__.py:233) wants
#                 SYMONEURAL_SESSION_SECRET of at least MIN_SECRET_CHARS=32 (:139), and minting a
#                 SYMONEURAL_ACCOUNTS_TOKEN here would write a key nothing reads. Its unit_state()
#                 at :865 says "if this ever becomes a rack unit" -- prospective, no row.
#   voice      -- backend/server.py:2317-2319 says in the source that the row is deliberately
#                 absent because href /voice.html does not exist. Switching it on would light
#                 nothing an operator can see; the page comes first, by that comment's rule.
#   exp        -- measured, not assumed: the row reads `queued` with the switch set and with
#                 it unset. gate.py:26-27 gates mutation only, so an arm would change no
#                 reading on the rack and its whole visible effect would be zero.
#   reinforce  -- the surface imports and serves without torch (the import is inside a
#                 function, apps/studio/plugins/reinforce/runner.py:299), and torch is not installed on this
#                 box. An arm would green a training surface whose every run fails. Installing
#                 torch is the prerequisite, and it is not this script's business.
#   mining     -- it already has a sanctioned path, and this would break it. load_env()
#                 (apps/cryptominer/__init__.py:134) merges apps/cryptominer/miner.env and
#                 never overrides an exported variable, so a key written here would be
#                 exported by EnvironmentFile= and permanently beat the file the package
#                 documents as the operator channel. SYMONEURAL_MINER_CMD cannot be invented either.
#   news       -- the switch is not a surface toggle, it is an outbound-network decision.
#                 Setting SYMONEURAL_NEWS_ENABLED=1 takes the box from "makes no outbound
#                 requests at all" (apps/news/__init__.py:20-21) to a periodic
#                 fetcher against eight third-party hosts, ~112 requests an hour on the
#                 default interval. There is also no token to mint -- the read endpoint is
#                 public and serves a cache -- so the loop's shape above, `_ENABLED=1` plus a
#                 fresh secret, does not fit it. It is switched by hand, deliberately, in the
#                 order recorded in the package README: deploy the site, set the variable,
#                 then restart.
#   discovery  -- there is nothing yet for the switch to switch. apps/studio/plugins/discovery has
#                 no router, no page and no rack row, and its __init__.py docstring says why
#                 in the terms api.py:2317-2319 set for voice: a row pointing at a 404 is
#                 worse than no row. So enabled() gates no endpoint and an arm here would
#                 write a key nothing reads. The two subcommands that work today, `search`
#                 and `stats`, need neither the switch nor a token; the half that is dark
#                 needs playwright installed and a provider key, and this script can supply
#                 neither. Same rule as voice -- the page comes first.
#   live       -- it is ALREADY ON, uniquely among the togglable surfaces, so there is nothing
#                 here to enable. enabled() (apps/live/routes.py) defaults true and writes the
#                 argument out: every other gated surface costs something the moment it is
#                 switched on -- the GPU, an outbound fetcher, a miner -- while this one serves
#                 files out of a directory that is empty unless OBS has been configured to
#                 write into it. Default-off had no safety to offer there; it could only
#                 produce a tab that was broken on arrival. So the only key worth writing for
#                 this surface is SYMONEURAL_LIVE_ENABLED=0, and this script's verb is enable:
#                 a tool named for turning surfaces on is the wrong place for the one
#                 default-on surface to be turned off, and an arm that wrote =1 would be a
#                 command that reports success and changes nothing -- exactly the half-fix
#                 test_every_argument_the_parser_accepts_writes_something exists to catch.
#                 There is no token to mint either: the video path holds no credential at all.
#                 The bridge's password lives in apps/live/symoneural-live.env at mode 600
#                 (see that package's README), which is a file this script must never touch.
#
# apps/test_enable_surfaces.py pins this list in both directions: it fails if a fifteenth
# gated switch appears, if one of these eight quietly gains an arm, and if a name is dropped
# from this block. Adding an arm means deciding here first, not discovering it from a rack row.

install -d -m 0755 "$DROPIN_DIR"
cat > "$DROPIN" <<EOF
# Written by scripts/enable-surfaces.sh. A drop-in rather than an edit to the unit, so
# re-running ops/deploy/install-service.sh does not silently switch these surfaces back off.
#
# The leading '-' means a missing file is not a startup failure: deleting $ENV_FILE
# turns every one of these surfaces off and the API still serves chat, image and calc.
# That is the intended panic button, and it must not brick the service.
[Service]
EnvironmentFile=-$ENV_FILE
EOF
chmod 0644 "$DROPIN"
printf 'Wrote %s\n' "$DROPIN"

systemctl daemon-reload
systemctl restart "$UNIT"

# ---------------------------------------------------------------- verify against the rack
#
# The rack is the check that matters. A unit reporting `ready` in /api/status is the same
# reading the site shows a visitor, so verifying here means verifying the thing the operator
# is actually going to look at -- not merely that a process started.
printf '\nWaiting for the API to answer...\n'
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null http://127.0.0.1:8800/api/status 2>/dev/null; then break; fi
  sleep 1
done

# Two shell facts, both learned by this block being broken from the day it was written:
#
#   * The reader below is a QUOTED heredoc, not `python3 -c '...'`. Inside a
#     single-quoted shell string a backslash-quote is a literal backslash followed by a
#     quote, so the f-strings reached Python as `u[\"id\"]` and it died with
#     "SyntaxError: unexpected character after line continuation character" on every run.
#     A quoted heredoc passes its body through untouched, so `u["id"]` stays `u["id"]`
#     and there is nothing to escape. Re-quoting the -c form would have worked too and is
#     the wrong fix: it leaves the next author one edit away from the same crash.
#   * The document arrives in an environment variable rather than on stdin, because the
#     heredoc *is* stdin. Piping curl into a command that also takes a heredoc cannot work.
#
# The two failure modes are reported separately now. The old `|| die` fired on the
# SyntaxError and printed "the API did not come back" -- which was false. The API had come
# back; the operator was sent to journalctl to hunt a service fault that was in this file.
STATUS_DOC=$(curl -fsS http://127.0.0.1:8800/api/status 2>/dev/null) \
  || die "/api/status did not answer after the restart -- journalctl -u $UNIT -n 50"

# `rack` is deliberately absent from the watch set below: it is the operator power switch,
# not a rack row, and it has no `id` in /api/status. Including it would print nothing and
# read like a surface that failed to come up.
STATUS_DOC="$STATUS_DOC" /usr/bin/python3 - <<'PYEOF' \
  || die "the API answered but its reply did not parse -- the fault is here, not the service"
import json, os, sys

try:
    doc = json.loads(os.environ["STATUS_DOC"])
except Exception as e:
    sys.exit(f"/api/status did not parse: {e}")
for u in doc.get("units", []):
    if u.get("id") in {"coder", "project", "studio", "gateway"}:
        print(f'  {u["id"]:<9} {u["state"]:<8} {u["detail"]}')
PYEOF

printf '\nDone. Tokens are in %s (root, 0600). Read one with:\n' "$ENV_FILE"
printf '    sudo sed -n "s/^SYMONEURAL_PROJECT_TOKEN=//p" %s\n' "$ENV_FILE"
printf '\nBoth Coder and Rack remain loopback-only: SYMONEURAL_*_ALLOW_REMOTE is deliberately unset.\n'
printf 'Studio is not loopback-gated in the same way -- it has no ALLOW_REMOTE switch, so its\n'
printf 'token is the whole gate. backend/studio/__init__.py:42 is explicit that\n'
printf 'the surface can write to the host. Treat SYMONEURAL_STUDIO_TOKEN accordingly.\n'
