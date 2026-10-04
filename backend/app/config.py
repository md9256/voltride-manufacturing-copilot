"""Application settings, read from environment variables (and the repo-root .env locally)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    odoo_mode: Literal["live", "demo"] = "live"
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_user: str = ""
    odoo_api_key: str = ""
    odoo_timeout_s: float = 15.0
    # Demo mode only; empty means the bundled snapshot (app/odoo/snapshot/voltride.json).
    odoo_snapshot_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
