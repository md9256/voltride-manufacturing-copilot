"""Alembic environment. Runs migrations synchronously with psycopg.

Uses the direct (non-pooled) Neon URL when available: DDL through a
transaction-mode pooler works but is slower and can hold pooled connections.
An explicit `sqlalchemy.url` (set by tests) takes precedence.
"""

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.models import chat  # noqa: F401  (registers tables on Base.metadata)
from app.models.db import Base


def sync_url() -> str:
    explicit = context.config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    s = get_settings()
    url = s.database_url_unpooled or s.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith(("postgresql://", "postgres://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    return url


def run() -> None:
    engine = create_engine(sync_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()
