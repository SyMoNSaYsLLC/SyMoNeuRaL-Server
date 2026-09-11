#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/google/Symoneural
cd "$ROOT"
mkdir -p .private/storage-reorg
chmod 700 .private/storage-reorg

echo '=== READ-ONLY STORAGE AUDIT ==='
python3 tools/sym_storage_audit.py

echo
echo '=== SAFE DRIVE REORGANIZATION PLAN (NO MUTATION) ==='
python3 tools/sym_drive_reorg.py plan

echo
echo '=== CURRENT CHECKPOINTED ORCHESTRATOR STATUS ==='
if [ -x tools/storage_reorg.py ]; then
  python3 tools/storage_reorg.py status || true
else
  echo 'tools/storage_reorg.py not present'
fi
