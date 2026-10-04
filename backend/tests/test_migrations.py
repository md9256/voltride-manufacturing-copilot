from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.models.db import Base, engine_args
from app.models.migrate import upgrade_to_head


def test_migrations_create_exactly_the_model_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        assert {"conversations", "messages"} <= set(inspect(conn).get_table_names())
        # Autogenerate finds no difference between the migrated database and
        # the SQLAlchemy models: they cannot drift apart unnoticed.
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    engine.dispose()


def test_neon_url_translated_for_asyncpg():
    target, connect_args = engine_args("postgresql://u:p@host/db?sslmode=require&channel_binding=require")
    assert target.drivername == "postgresql+asyncpg"
    assert dict(target.query) == {}
    assert connect_args == {"statement_cache_size": 0, "ssl": "require"}


def test_non_postgres_url_untouched():
    assert engine_args("sqlite+aiosqlite://") == ("sqlite+aiosqlite://", {})
