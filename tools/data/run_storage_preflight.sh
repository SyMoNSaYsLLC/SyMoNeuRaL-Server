#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/google/Symoneural
cd "$ROOT"
mkdir -p .private/storage-reorg
chmod 700 .private/storage-reorg

echo '=== READ-ONLY STORAGE AUDIT ==='
python3 tools/audit/sym_storage_audit.py

echo
echo '=== SAFE DRIVE REORGANIZATION PLAN (NO MUTATION) ==='
python3 tools/data/sym_drive_reorg.py plan

echo
echo '=== CURRENT CHECKPOINTED ORCHESTRATOR STATUS ==='
if [ -x tools/data/storage_reorg.py ]; then
  python3 tools/data/storage_reorg.py status || true
else
  echo 'tools/data/storage_reorg.py not present'
fi
