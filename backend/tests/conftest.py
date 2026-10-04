import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.models import actions, chat  # noqa: F401  (registers tables)
from app.models.db import Base
from app.security import ai_limiter, login_limiter


@pytest.fixture(autouse=True)
def isolated_security(monkeypatch):
    """Every test starts with empty rate limits and no demo password, whatever
    the local .env says; tests/test_security.py turns the password on."""
    monkeypatch.setattr(get_settings(), "demo_password", "")
    monkeypatch.setattr(get_settings(), "auth_secret", "test-secret")
    ai_limiter.reset()
    login_limiter.reset()
    yield


class SqliteDb:
    """An in-memory SQLite database shared by every session (StaticPool).

    Tables are created lazily on first use, so the engine's single connection
    is opened in whichever event loop uses it (pytest's, or TestClient's).
    """

    def __init__(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self._ready = False

    async def sessionmaker(self) -> async_sessionmaker:
        if not self._ready:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self._ready = True
        return self.maker


@pytest.fixture
async def db():
    database = SqliteDb()
    maker = await database.sessionmaker()
    async with maker() as session:
        yield session
    await database.engine.dispose()
