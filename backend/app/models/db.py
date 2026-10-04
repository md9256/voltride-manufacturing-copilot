"""Async SQLAlchemy engine and session factory for the app database."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import JSON, URL, make_url
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# JSONB on Postgres (indexable, compact); plain JSON elsewhere (SQLite in tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class DatabaseNotConfigured(RuntimeError):
    pass


def engine_args(url: str) -> tuple[URL | str, dict]:
    """Translate a Neon-style `postgresql://...?sslmode=require` URL for asyncpg.

    asyncpg (chosen over async psycopg, which cannot run on Windows' default
    event loop) takes SSL settings as a connect argument rather than libpq URL
    parameters, so those are moved out of the query string.
    """
    if not url.startswith(("postgresql://", "postgres://")):
        return url, {}  # e.g. sqlite+aiosqlite:// in tests
    parsed = make_url(url).set(drivername="postgresql+asyncpg")
    query = dict(parsed.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # libpq-only option
    connect_args: dict = {
        # Neon's pooled endpoint is PgBouncer in transaction mode: a cached
        # prepared statement may land on a different server connection, so
        # asyncpg's statement cache is disabled.
        "statement_cache_size": 0,
    }
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = "require"
    return parsed.set(query=query), connect_args


def make_engine(url: str) -> AsyncEngine:
    target, connect_args = engine_args(url)
    return create_async_engine(target, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    return make_engine(url)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_sessionmaker()() as session:
        yield session
