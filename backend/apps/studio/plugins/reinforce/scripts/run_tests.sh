#!/usr/bin/env bash
# Test runner for symoneural_reinforce.
#
# Encodes the four hardware constraints found in the local CUDA audit:
#
#   1. greenContext            -- never auto-split on 70 SMs; use --split 8,8
#   2. reductionMultiBlockCG   -- NVRTC needs CUDA include dir AND cuda-cccl
#                                 libcu++ headers, colon-separated
#   3. multiGPUGradientAverage -- launch via mpirun --oversubscribe -np 2
#   4. simpleP2P               -- check topology first; waive, do not fail
#
# ENVIRONMENT ISOLATION: this script never touches
# cuda-samples/python/.venv. It builds its own venv under /tmp (override with
# SYMO_VENV) and installs only there.
#
# Usage:
#   scripts/run_tests.sh                 # full suite
#   scripts/run_tests.sh --quick         # skip slow/benchmark tests
#   scripts/run_tests.sh --bench         # tests + benchmark suite
#   scripts/run_tests.sh --setup-only    # just build the venv

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYMO_VENV="${SYMO_VENV:-/tmp/symoneural-venv}"
PY="$SYMO_VENV/bin/python"

QUICK=0; BENCH=0; SETUP_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --quick)      QUICK=1 ;;
    --bench)      BENCH=1 ;;
    --setup-only) SETUP_ONLY=1 ;;
    -h|--help)    sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------
# Guard: never install into the user's primary venv
# --------------------------------------------------------------------------
PROTECTED="$(cd "$REPO/.." 2>/dev/null && pwd)/cuda-samples/python/.venv"
case "$SYMO_VENV" in
  "$PROTECTED"|"$PROTECTED"/*)
    echo "REFUSING: SYMO_VENV points at the protected primary venv:" >&2
    echo "  $PROTECTED" >&2
    echo "Pick a path under /tmp instead." >&2
    exit 1 ;;
esac

echo "==> repo : $REPO"
echo "==> venv : $SYMO_VENV  (isolated; primary .venv untouched)"

# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
if [[ ! -x "$PY" ]]; then
  echo "==> creating isolated venv"
  python3 -m venv "$SYMO_VENV"
  "$SYMO_VENV/bin/pip" install --quiet --upgrade pip
  echo "==> installing requirements"
  "$SYMO_VENV/bin/pip" install --quiet -r "$REPO/requirements.txt"
fi

# --------------------------------------------------------------------------
# Constraint 2 -- build the colon-separated NVRTC include path
# --------------------------------------------------------------------------
# cooperative_groups.h pulls in <cuda/std/type_traits>, which lives in the
# cuda-cccl package, NOT in the CUDA toolkit include dir. Passing only one
# gives: catastrophic error: cannot open source file "cuda/std/type_traits"
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
CCCL_INC="$SITE/cuda/cccl/headers/include"
CUDA_INC=""
for c in /usr/local/cuda/targets/x86_64-linux/include \
         /usr/local/cuda/include "$SITE/nvidia/cu13/include"; do
  [[ -d "$c" ]] && CUDA_INC="$c" && break
done

if [[ -d "$CCCL_INC" && -n "$CUDA_INC" ]]; then
  export SYMONEURAL_CUDA_INCLUDE="$CUDA_INC:$CCCL_INC"
  echo "==> NVRTC -I : $SYMONEURAL_CUDA_INCLUDE"
else
  echo "==> WARNING: libcu++ headers not found; cooperative-group tests will waive"
  echo "             fix: $SYMO_VENV/bin/pip install 'cuda-cccl[cu13]>=1.0.0'"
fi

# --------------------------------------------------------------------------
# Constraint 1 -- green context split (never auto on a 70-SM part)
# --------------------------------------------------------------------------
export SYMONEURAL_GREEN_SPLIT="${SYMONEURAL_GREEN_SPLIT:-8,8}"
echo "==> green split : --split $SYMONEURAL_GREEN_SPLIT (auto-split is rejected on 70 SMs)"

# --------------------------------------------------------------------------
# Constraints 3 & 4 -- MPI launcher and GPU topology
# --------------------------------------------------------------------------
NGPU="$("$PY" -c '
try:
    from cuda.core import Device
    print(len(Device.get_all_devices()))
except Exception:
    print(0)
' 2>/dev/null || echo 0)"
echo "==> GPUs : $NGPU $([[ "$NGPU" -lt 2 ]] && echo '(P2P tests will waive, not fail)')"

if command -v mpirun >/dev/null 2>&1; then
  echo "==> MPI  : mpirun --oversubscribe -np 2"
else
  echo "==> MPI  : mpirun NOT FOUND -- MPI tests will waive"
  echo "           fix: sudo apt install openmpi-bin"
fi

[[ "$SETUP_ONLY" -eq 1 ]] && { echo "==> setup complete"; exit 0; }

# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
cd "$REPO"
PYTEST_ARGS=(-v --strict-markers)
[[ "$QUICK" -eq 1 ]] && PYTEST_ARGS+=(-m "not slow")

echo
echo "==> pytest"
"$PY" -m pytest "${PYTEST_ARGS[@]}"
STATUS=$?

# Constraint 3 -- MPI-backed work runs under a launcher, oversubscribed so a
# single-GPU box still exercises the two-rank path.
if command -v mpirun >/dev/null 2>&1; then
  echo
  echo "==> MPI collective check (mpirun --oversubscribe -np 2)"
  cat > /tmp/symo_mpi_check.py <<'PYEOF'
from mpi4py import MPI
import numpy as np
comm = MPI.COMM_WORLD
rank, size = comm.Get_rank(), comm.Get_size()
local = np.full(1024, float(rank + 1), dtype=np.float32)
avg = np.empty_like(local)
comm.Allreduce(local, avg, op=MPI.SUM)
avg /= size
expected = sum(range(1, size + 1)) / size
ok = np.allclose(avg, expected)
if rank == 0:
    print(f"  ranks={size} allreduce_mean={avg[0]:.4f} expected={expected:.4f} "
          f"{'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
PYEOF
  mpirun --oversubscribe -np 2 "$PY" /tmp/symo_mpi_check.py || STATUS=1
  rm -f /tmp/symo_mpi_check.py
fi

if [[ "$BENCH" -eq 1 ]]; then
  echo
  echo "==> benchmark suite"
  "$PY" -m bench.run_all $([[ "$QUICK" -eq 1 ]] && echo --quick)
fi

echo
echo "==> primary .venv verification"
PRIMARY="$PROTECTED"
if [[ -x "$PRIMARY/bin/pip" ]]; then
  N="$("$PRIMARY/bin/pip" freeze | wc -l)"
  echo "    $PRIMARY: $N packages $([[ "$N" -eq 7 ]] && echo '(pristine)' || echo '(CHANGED -- expected 7)')"
else
  echo "    (primary venv not present; nothing to verify)"
fi

exit "$STATUS"
