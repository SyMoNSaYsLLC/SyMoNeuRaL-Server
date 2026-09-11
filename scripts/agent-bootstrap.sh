#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "================ SyMoNeuRaL agent bootstrap ================"
echo "repo: $ROOT"
echo "head: $(git rev-parse --short HEAD)"
echo

echo "================ canonical git identity ================"
git config --local user.name "gpmcdonald"
git config --local user.email "garrettmcdonald87@gmail.com"
git config --local --get user.name
git config --local --get user.email
echo

echo "================ required reading ================"
for f in \
  CLAUDE.md \
  .claude/CLAUDE.md \
  .claude/HANDOVER.md \
  docs/ENGINEERING.md \
  docs/ops/MEASUREMENTS.md \
  docs/ops/EXPORTS.md \
  PROJECT-TASKS.md
do
  if [ -e "$f" ]; then
    echo "OK   $f"
  else
    echo "MISS $f"
  fi
done
echo

echo "================ current status ================"
git status --short
echo

echo "================ lock check ================"
if [ -e .git/index.lock ]; then
  echo "RED: .git/index.lock exists"
  ls -la .git/index.lock
  exit 1
else
  echo "no index.lock"
fi

echo "================ bootstrap complete ================"
