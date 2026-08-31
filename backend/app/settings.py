"""Application configuration (12-factor: everything from env vars with defaults).

Values come from environment variables, optionally seeded by a local ``.env`` file
during development. In the Docker image these are supplied by docker-compose.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "NAS Sync Manager"
    app_version: str = "1.0.0"

    # --- Server ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # --- Database ---
    # In the container this is sqlite:////data/nas_sync.db (absolute, on the volume).
    # For local dev it defaults to a file under ./data next to the backend.
    database_url: str = "sqlite:///./data/nas_sync.db"

    # --- Security ---
    # Fernet key used to encrypt FTP passwords at rest. Generated on first run
    # (Stage 1) and persisted to the .env file if not supplied here.
    app_secret: str | None = None

    # --- rsync transport ---
    # Where NAS shares are bind-mounted inside the container. A host path /X is
    # mounted at <mount_root>/X, so the container path encodes the host path.
    # See app/services/mounts.py and the volumes block in docker-compose.prod.yml.
    mount_root: str = "/nas"

    # --- Behaviour defaults (overridable per-job / via Settings page later) ---
    timezone: str = "Europe/London"

    # Start the background scheduler on boot (disabled in tests).
    scheduler_autostart: bool = True

    # --- CORS (only needed for split-origin local dev; nginx proxies in prod) ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
