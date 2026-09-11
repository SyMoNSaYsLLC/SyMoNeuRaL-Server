#!/usr/bin/env bash
# Build the two isolated toolchains the Gateway's operator side needs.
#
#   ./ops/gateway/setup.sh
#
# Neither of them may ever enter the serving path. `.claude/CLAUDE.md` pins the API to OS
# packages and forbids `pip install` into that interpreter; the deny rules in
# `.claude/settings.local.json` block the bare forms for exactly that reason. Everything here
# installs by full path into a directory beside this script.
#
#   .venv/   tronpy -- signing and broadcasting. Used ONLY by gateway-cli.py.
#   .solc/   solc 0.8.18 and a local EVM -- used ONLY by build.mjs and test_contracts.mjs.
#
# Both are gitignored and both are rebuildable from this script, which is why `artifacts/` is
# committed and they are not: a deployment must never need a compiler to be reproducible.
#
# Nothing here derives its location from anything but its own path, per `.claude/HANDOVER.md`
# §0 — clone the repo anywhere and this works.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "==> python venv for tronpy (signing side)"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --disable-pip-version-check --upgrade pip
# coincurve is named explicitly even though tronpy already requires it. tronpy signs through
# coincurve (libsecp256k1) when it is importable and through the pure-Python `ecdsa` package
# when it is not -- and only the former normalises s into the lower half of the curve order.
# The contract REJECTS high-s, so the silent fallback would revert roughly half of all quotes
# at the buyer's expense. gateway-cli.py checks the property at signing time as well; this line
# is so the failure cannot be introduced by a future tronpy dropping the dependency.
./.venv/bin/pip install --quiet --disable-pip-version-check tronpy coincurve
./.venv/bin/python -c "import tronpy, coincurve; print('    tronpy ok, coincurve ok')"

echo "==> node toolchain for solc + the local EVM (contract side)"
mkdir -p .solc
cd .solc
# solc is pinned BELOW 0.8.20 on purpose: 0.8.20+ emits PUSH0, which the TVM does not
# implement, and such a contract deploys and then reverts on its first call. build.mjs asserts
# the version it actually got rather than trusting this line.
npm install --no-audit --no-fund --loglevel=error \
  solc@0.8.18 '@ethereumjs/evm@3.1.0' '@noble/curves'
cd "$HERE"

echo "==> compiling contracts"
node build.mjs

echo "==> executing them in a local EVM"
node test_contracts.mjs

echo
echo "Ready. Next steps are in ops/gateway/DEPLOY.md."
echo "Nothing above has touched a chain, a key, or any money."
