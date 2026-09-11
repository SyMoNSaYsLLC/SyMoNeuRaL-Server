\
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict
import time


@dataclass
class WorkerStatus:
    ts: float
    ok: bool
    state: str
    miner_pid: int | None
    miner_uptime_s: int | None
    gpu: Dict[str, Any]
    note: str | None


def write_status(path: Path, status: WorkerStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(asdict(status), f, indent=2, sort_keys=True)
    tmp.replace(path)


def now_ts() -> float:
    return time.time()
