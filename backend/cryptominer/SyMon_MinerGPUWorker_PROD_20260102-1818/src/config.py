from __future__ import annotations
\

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mining_enabled: bool
    miner_cmd: str
    gpu_index: int
    status_interval_s: int
    log_level: str
    workdir: Path
    status_file: Path
    nvidia_smi: str


def load_settings() -> Settings:
    load_dotenv()

    workdir = Path(os.getenv("SYM_WORKDIR", ".")).resolve()
    status_file = Path(os.getenv("SYM_STATUS_FILE", "data/status.json"))
    if not status_file.is_absolute():
        status_file = (workdir / status_file).resolve()

    return Settings(
        mining_enabled=_env_bool("SYM_MINING_ENABLED", False),
        miner_cmd=os.getenv("SYM_MINER_CMD", "").strip(),
        gpu_index=_env_int("SYM_GPU_INDEX", 0),
        status_interval_s=_env_int("SYM_STATUS_INTERVAL_S", 5),
        log_level=(os.getenv("SYM_LOG_LEVEL", "INFO").strip().upper() or "INFO"),
        workdir=workdir,
        status_file=status_file,
        nvidia_smi=(os.getenv("SYM_NVIDIA_SMI", "nvidia-smi").strip() or "nvidia-smi"),
    )
