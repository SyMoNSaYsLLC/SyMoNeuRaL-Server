from __future__ import annotations
\

import sys
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
sys.path.insert(0, str(ROOT))

from src.worker import main

if __name__ == "__main__":
    raise SystemExit(main())
