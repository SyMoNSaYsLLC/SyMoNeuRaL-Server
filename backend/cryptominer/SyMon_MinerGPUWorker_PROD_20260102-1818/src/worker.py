\
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from pathlib import Path

import psutil

from .config import load_settings
from .nvidia import read_gpu_quick
from .status import WorkerStatus, write_status, now_ts


def _setup_logging(log_level: str, logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "worker.log"

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def _parse_cmd(cmd: str) -> list[str]:
    return shlex.split(cmd, posix=False)


def _start_miner(cmd: str, workdir: Path, env: dict) -> subprocess.Popen:
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_f = open(logs_dir / "miner_stdout.log", "a", encoding="utf-8")
    err_f = open(logs_dir / "miner_stderr.log", "a", encoding="utf-8")

    return subprocess.Popen(
        _parse_cmd(cmd),
        cwd=str(workdir),
        env=env,
        stdout=out_f,
        stderr=err_f,
        text=True,
    )


def _proc_uptime_s(pid: int) -> int | None:
    try:
        p = psutil.Process(pid)
        return max(0, int(time.time() - p.create_time()))
    except Exception:
        return None


def main() -> int:
    s = load_settings()

    if not s.mining_enabled:
        print("Refusing to start: SYM_MINING_ENABLED != 1")
        print("Edit .env and set SYM_MINING_ENABLED=1 when you are ready.")
        return 2

    if not s.miner_cmd:
        print("Refusing to start: SYM_MINER_CMD is empty.")
        print("Set SYM_MINER_CMD in .env to your miner binary + args.")
        return 2

    _setup_logging(s.log_level, s.workdir / "logs")
    log = logging.getLogger("worker")

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(s.gpu_index)
    env.setdefault("NVIDIA_VISIBLE_DEVICES", str(s.gpu_index))

    log.info("Starting miner worker")
    log.info("Workdir: %s", s.workdir)
    log.info("GPU index: %s", s.gpu_index)

    proc = None
    try:
        proc = _start_miner(s.miner_cmd, s.workdir, env)
        log.info("Miner started with PID=%s", proc.pid)

        while True:
            code = proc.poll()
            gpu = read_gpu_quick(s.nvidia_smi, s.gpu_index)

            if code is None:
                status = WorkerStatus(
                    ts=now_ts(),
                    ok=True,
                    state="running",
                    miner_pid=proc.pid,
                    miner_uptime_s=_proc_uptime_s(proc.pid),
                    gpu=gpu,
                    note=None,
                )
                write_status(s.status_file, status)
            else:
                status = WorkerStatus(
                    ts=now_ts(),
                    ok=False,
                    state=f"exited({code})",
                    miner_pid=proc.pid,
                    miner_uptime_s=_proc_uptime_s(proc.pid),
                    gpu=gpu,
                    note="Miner process exited. Check logs/miner_stderr.log",
                )
                write_status(s.status_file, status)
                log.error("Miner exited with code=%s", code)
                return 10

            time.sleep(max(1, s.status_interval_s))

    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt: stopping miner")
        return 0
    except Exception as e:
        log.exception("Worker error: %s", e)
        return 1
    finally:
        if proc is not None and proc.poll() is None:
            try:
                psutil.Process(proc.pid).terminate()
                log.info("Sent terminate to miner PID=%s", proc.pid)
            except Exception:
                pass
