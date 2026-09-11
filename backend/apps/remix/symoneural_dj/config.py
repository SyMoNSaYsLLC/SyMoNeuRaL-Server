"""Settings, loaded once from the environment (.env honoured via python-dotenv).

Missing Spotify credentials are not fatal at import time — the server must
still start so /health answers — they fail with a readable error the first
time the OAuth flow needs them (spotify.SpotifyAuthError).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    symon_url: str
    vllm_api_key: str
    dj_token: str  # break-glass OWNER bearer (empty => loopback peers only)
    token_path: Path
    host: str
    port: int
    accounts_db: Path  # shared accounts+billing db (symoneural_accounts)
    secure_cookies: bool  # True behind TLS in production
    playlist_cost: int  # SyMoN tokens charged per playlist (owner free)
    capture_dir: Path  # distill store the data-pump writes training pairs into


def load_settings(env_file: str | os.PathLike | None = None) -> Settings:
    load_dotenv(env_file)  # no-op when absent; real environment wins over .env
    return Settings(
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        spotify_client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        spotify_redirect_uri=os.environ.get(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8090/auth/callback"
        ),
        symon_url=os.environ.get("SYMON_URL", "http://127.0.0.1:9001"),
        vllm_api_key=os.environ.get("VLLM_API_KEY", ""),
        dj_token=os.environ.get("DJ_TOKEN", ""),
        token_path=Path(os.environ.get("DJ_TOKEN_PATH", ".run/spotify_tokens.json")),
        host=os.environ.get("DJ_HOST", "0.0.0.0"),
        port=int(os.environ.get("DJ_PORT", "8090")),
        accounts_db=Path(os.environ.get("DJ_ACCOUNTS_DB", ".run/accounts.db")),
        secure_cookies=os.environ.get("DJ_SECURE_COOKIES", "0") in ("1", "true", "yes"),
        playlist_cost=int(os.environ.get("DJ_PLAYLIST_COST", "1")),
        capture_dir=Path(os.environ.get(
            "SYMON_DISTILL_DIR",
            Path(__file__).resolve().parents[2] / "symon_llm" / "studio" / "data" / "distill")),
    )
