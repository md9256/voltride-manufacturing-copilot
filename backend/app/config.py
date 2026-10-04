"""Application settings, read from environment variables (and the repo-root .env locally)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Pinned versions, not "-latest" aliases: an alias can move to a model with a
# different free-tier quota (gemini-flash-latest started sharing
# gemini-3.8-flash's 20 requests/day) and change behaviour without a deploy.
DEFAULT_MODELS = {"gemini": "gemini-3.5-flash", "anthropic": "claude-opus-5-5"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    odoo_mode: Literal["live", "demo"] = "live"
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_user: str = ""
    odoo_api_key: str = ""
    # Optional key of a separate Odoo user (Purchase rights only) for confirmed writes.
    odoo_write_api_key: str = ""
    odoo_timeout_s: float = 15.0
    # Demo mode only; empty means the bundled snapshot (app/odoo/snapshot/voltride.json).
    odoo_snapshot_path: str = ""

    # App database (chat history). Neon's pooled URL in production.
    database_url: str = ""
    # Direct (non-pooled) URL for migrations; falls back to database_url.
    database_url_unpooled: str = ""

    # LLM. `gemini` and `openai_compatible` share one adapter (OpenAI chat
    # completions protocol); `anthropic` uses the Anthropic SDK.
    llm_provider: Literal["gemini", "anthropic", "openai_compatible"] = "gemini"
    llm_model: str = ""  # empty: DEFAULT_MODELS[llm_provider]
    llm_effort: Literal["", "low", "medium", "high", "xhigh", "max"] = ""  # Anthropic only; empty = model default
    llm_base_url: str = ""  # openai_compatible only (e.g. Hugging Face router, Groq)
    llm_api_key: str = ""  # openai_compatible only
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS.get(self.llm_provider, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
