import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import chat  # noqa: F401  (registers tables)
from app.models.db import Base


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
