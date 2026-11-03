"""SQLite (WAL) async engine, session factory and table creation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings
from .models.base import Base

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001, ANN202
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA cache_size=-64000;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Bring the database schema up to date with Alembic migrations.

    Startup no longer calls ``create_all``: the schema is created and
    evolved only by migrations in ``backend/alembic/versions/``. The
    migration runs synchronously (Alembic is sync-only) in a thread so
    the async lifespan is not blocked. Seeding (scripts/seed-baselines.py)
    runs separately, after migrations, and calls this same function.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    def _migrate() -> str:
        # Databases created by the old create_all startup already have
        # the tables but no alembic_version row: stamp them at head
        # instead of re-running the initial migration (which would fail
        # on duplicate tables). Fresh databases get a real upgrade.
        sync_url = settings.DATABASE_URL.replace(
            "sqlite+aiosqlite://", "sqlite://"
        )
        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                dialect = conn.dialect
                has_version = dialect.has_table(conn, "alembic_version")
                has_tables = dialect.has_table(conn, "checks")
        finally:
            engine.dispose()
        if has_tables and not has_version:
            # One-time adoption for databases created by the old
            # create_all startup: create only the tables that are
            # missing (chat/watchlist, added later), then stamp at
            # head. Fresh databases never take this path.
            from . import models  # noqa: F401  (register models)
            from .models.base import Base

            create_engine2 = create_engine(sync_url)
            try:
                with create_engine2.begin() as conn:
                    Base.metadata.create_all(conn)
            finally:
                create_engine2.dispose()
            command.stamp(cfg, "head")
            return "stamped"
        command.upgrade(cfg, "head")
        return "upgraded"

    await asyncio.to_thread(_migrate)
