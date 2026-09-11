"""uvicorn entry point: `uvicorn symoneural_dj.main:app` (run.sh does this)."""
from .app import create_app

app = create_app()
