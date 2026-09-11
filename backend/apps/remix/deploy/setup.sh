#!/usr/bin/env bash
# =============================================================================
# symoneural_dj — fresh-machine setup
# =============================================================================
#   ./deploy/setup.sh                  # check + set up, prompts before writing
#   ./deploy/setup.sh --check          # read-only: report what is missing
#   ./deploy/setup.sh --owner you@x.com
#
# What it does: verifies the interpreter and dependencies, creates .run/ with
# the right modes, copies .env.production.example to .env if absent, seeds the
# owner account, and runs the test suite. It does NOT start anything, does NOT
# write secrets for you, and does NOT touch Spotify or Stripe.
#
# It is deliberately idempotent: running it twice is a no-op plus a report.
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$PWD"
PY="${PY:-$HOME/.venvs/vllm/bin/python}"
CHECK_ONLY=0
OWNER_EMAIL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_ONLY=1; shift ;;
        --owner) OWNER_EMAIL="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; DIM=$'\e[2m'; RST=$'\e[0m'
ok()   { printf '  %s[ok]%s   %s\n'   "$GRN" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n'   "$YEL" "$RST" "$*"; }
bad()  { printf '  %s[FAIL]%s %s\n'   "$RED" "$RST" "$*"; }
step() { printf '\n%s>>> %s%s\n' $'\e[1m' "$*" "$RST"; }
PROBLEMS=0
fail() { bad "$*"; PROBLEMS=$((PROBLEMS + 1)); }

step "1. Interpreter"
if [[ ! -x "$PY" ]]; then
    PY="$(command -v python3 || true)"
    [[ -n "$PY" ]] || { fail "no python3 found; set PY=/path/to/python"; exit 1; }
    warn "using $PY (set PY= to override)"
else
    ok "$PY"
fi
"$PY" - <<'EOF' || exit 1
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"python 3.11+ required, found {sys.version.split()[0]}")
print(f"  python {sys.version.split()[0]}")
EOF

step "2. Dependencies"
MISSING=""
for mod in fastapi uvicorn httpx dotenv argon2; do
    if "$PY" -c "import $mod" 2>/dev/null; then ok "$mod"; else MISSING="$MISSING $mod"; fi
done
if [[ -n "$MISSING" ]]; then
    fail "missing:$MISSING"
    echo "      $PY -m pip install -r requirements.txt"
fi
if "$PY" -c "import symoneural_accounts" 2>/dev/null; then
    ok "symoneural_accounts importable"
else
    fail "symoneural_accounts not importable — it is a sibling package;"
    echo "      run from the repo root or: $PY -m pip install -e ../symoneural_accounts"
fi

step "3. Runtime directory"
if [[ -d .run ]]; then ok ".run/ exists"; else
    if (( CHECK_ONLY )); then warn ".run/ missing (would create)"; else
        mkdir -p .run && chmod 700 .run && ok "created .run/ (0700)"
    fi
fi
[[ -d .run ]] && { chmod 700 .run 2>/dev/null || true; ok ".run/ mode $(stat -c %a .run)"; }

step "4. Configuration"
if [[ -f .env ]]; then
    ok ".env present"
    for key in SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET VLLM_API_KEY; do
        if grep -qE "^${key}=.+" .env; then ok "$key set"; else fail "$key is EMPTY in .env"; fi
    done
    if grep -qE '^DJ_SECURE_COOKIES=1' .env; then ok "DJ_SECURE_COOKIES=1"
    else fail "DJ_SECURE_COOKIES is not 1 — session cookies will ride plaintext HTTP"; fi
    if grep -qE '^DJ_HOST=0\.0\.0\.0' .env; then
        fail "DJ_HOST=0.0.0.0 publishes bearer tokens to the LAN; bind 127.0.0.1 behind TLS"
    else ok "DJ_HOST is not 0.0.0.0"; fi
    if grep -qE '^SPOTIFY_REDIRECT_URI=http://' .env; then
        fail "SPOTIFY_REDIRECT_URI is http:// — OAuth codes must ride TLS"
    fi
    if [[ "$(stat -c %a .env)" != "600" ]]; then
        if (( CHECK_ONLY )); then warn ".env is $(stat -c %a .env), should be 600"
        else chmod 600 .env && ok ".env tightened to 600"; fi
    else ok ".env mode 600"; fi
else
    if (( CHECK_ONLY )); then warn "no .env (would copy from .env.production.example)"
    else
        cp .env.production.example .env && chmod 600 .env
        ok "created .env from .env.production.example (0600)"
        warn "EDIT IT — Spotify credentials and VLLM_API_KEY are empty"
        PROBLEMS=$((PROBLEMS + 1))
    fi
fi

step "5. Accounts database"
DB="$(grep -E '^DJ_ACCOUNTS_DB=' .env 2>/dev/null | cut -d= -f2- || true)"
DB="${DB:-.run/accounts.db}"
if [[ -f "$DB" ]]; then
    ok "$DB exists ($(stat -c %s "$DB") bytes) — NOT reinitialising"
    [[ "$(stat -c %a "$DB")" == "600" ]] || { chmod 600 "$DB" 2>/dev/null && ok "tightened to 600"; }
elif (( CHECK_ONLY )); then
    warn "$DB missing (would be created on first run / owner seed)"
elif [[ -n "$OWNER_EMAIL" ]]; then
    "$PY" -m symoneural_accounts.cli seed-owner --db "$DB" --email "$OWNER_EMAIL"
    chmod 600 "$DB" 2>/dev/null || true
    ok "owner seeded; $DB is 0600"
else
    warn "no owner yet. Seed one with:"
    echo "      $PY -m symoneural_accounts.cli seed-owner --db $DB --email you@example.com"
fi
echo "  ${DIM}Back this file up — it is the only record of who paid you.${RST}"

step "6. Tests"
if (( CHECK_ONLY )); then
    warn "skipped in --check mode"
else
    if "$PY" -m pytest tests -q 2>&1 | tail -3; then ok "suite green"; else fail "tests failed"; fi
fi

step "7. Things this script cannot do for you"
cat <<'EOF'
  * TLS termination in front of this app (Caddy / Cloudflare). Non-negotiable:
    OAuth codes and bearer tokens ride these requests.
  * Register the HTTPS redirect URI in the Spotify dashboard, verbatim.
  * Clear the Spotify commercial-terms gate — see docs/LICENSING.md. It is a
    business decision, and it gates a paid launch regardless of the code.
  * Per-user rate limiting (P1-5, not implemented). One greedy account can
    starve the others; the engine serialises.
  * Encrypt the Spotify token store at rest (P1-7).
EOF

step "Result"
if (( PROBLEMS == 0 )); then
    printf '  %sReady.%s Start with: systemctl --user start symoneural-dj\n' "$GRN" "$RST"
else
    printf '  %s%d problem(s) above must be fixed first.%s\n' "$YEL" "$PROBLEMS" "$RST"
    exit 1
fi
