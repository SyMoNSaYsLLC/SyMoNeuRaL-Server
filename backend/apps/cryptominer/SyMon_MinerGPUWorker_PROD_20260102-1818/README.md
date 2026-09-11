# SyMon Miner GPU Worker (PROD)

A **GPU-first** worker that runs an external mining engine on your **NVIDIA RTX 5070 Ti** and provides:
- A single config surface (`.env`)
- Safety rails (owner-only operation, explicit enable flag)
- Live status JSON output for dashboards or monitoring
- Log files + clean start/stop behavior

> Reality check: writing a performant CUDA mining kernel from scratch is not a “small script” project.
> This worker is the clean, reusable orchestration layer that runs *any* miner binary you choose,
> while keeping your workflow standardized.

## Quick start (Windows PowerShell 7)

1) Put your miner binary somewhere (example):
- `C:\Tools\miners\miner.exe`

2) Copy `.env.example` → `.env` and edit the values.

3) Run:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_worker.py
```

## Outputs
- `data/status.json` updated every few seconds
- `logs/worker.log` rolling logs
- `logs/miner_stdout.log` / `logs/miner_stderr.log`

## Hard rules (so you stay safe)
- This is for **hardware you own** or **have explicit owner permission** to operate.
- The worker will **refuse to start** unless `SYM_MINING_ENABLED=1`.

## Notes
- Point `SYM_MINER_CMD` at any miner that supports your algorithm/pool.
- If your miner supports an HTTP API, you can add a parser later; for now we track process health and basic GPU telemetry (via `nvidia-smi` if available).
