"""Apply Alembic migrations programmatically (used at API startup)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def upgrade_to_head(url: str | None = None) -> None:
    """Upgrade the database to the latest revision. `url` overrides the
    configured DATABASE_URL (tests pass a SQLite URL)."""
    config = Config(str(ALEMBIC_INI))
    if url:
        config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
