"""Web-app configuration, separate from the engine's ``src/config.py``.

Only what the HTTP layer needs: where the compose config lives, CORS origins
for local dev, and the session TTL/exchange budget.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Master repo root — this file is <root>/app/config.py.
ROOT_DIR = Path(__file__).resolve().parent.parent
# The two-agent compose config the backend drives.
COMPOSE_CONFIG = ROOT_DIR / "agent" / "config.yaml"


class WebSettings(BaseSettings):
    """Settings for the FastAPI app.

    Attributes:
        cors_origins: Allowed browser origins (the Vite dev server).
        session_ttl_seconds: Idle lifetime of a conversation session.
        max_exchanges: Question budget per session before it resets.
        invocation_timeout_seconds: Ceiling on one agent invocation.
    """

    model_config = SettingsConfigDict(
        env_prefix="REPOMAP_WEB_",
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    session_ttl_seconds: int = 1800
    max_exchanges: int = 20
    invocation_timeout_seconds: float = 300.0


@lru_cache(maxsize=1)
def get_web_settings() -> WebSettings:
    """Return the process-wide web settings singleton.

    Returns:
        The cached :class:`WebSettings` instance.
    """
    return WebSettings()
