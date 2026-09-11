\
from __future__ import annotations

import subprocess
from typing import Any, Dict


def read_gpu_quick(nvidia_smi: str, gpu_index: int) -> Dict[str, Any]:
    """Best-effort GPU telemetry using nvidia-smi (no NVML dependency)."""
    cmd = [
        nvidia_smi,
        "--query-gpu=name,temperature.gpu,power.draw,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
        "-i",
        str(gpu_index),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=2).strip()
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 6:
            return {
                "name": parts[0],
                "temp_c": int(float(parts[1])),
                "power_w": float(parts[2]),
                "util_pct": int(float(parts[3])),
                "mem_used_mb": int(float(parts[4])),
                "mem_total_mb": int(float(parts[5])),
            }
        return {"raw": out}
    except Exception as e:
        return {"error": str(e), "gpu_index": gpu_index}
