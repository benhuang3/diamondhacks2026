"""Async SQLAlchemy engine + session factory for SQLite (aiosqlite)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import settings
from src.db.schema import Base

# Module-level engine + session factory. Created at import time; safe because
# create_async_engine is lazy about establishing connections.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create all tables idempotently. Call at FastAPI startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a session with commit/rollback handling."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
