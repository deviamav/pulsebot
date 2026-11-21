"""Async SQLAlchemy session factory."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import PostgresSettings


def build_engine(settings: PostgresSettings) -> AsyncEngine:
    """Create configured async engine."""
    return create_async_engine(
        settings.dsn,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory bound to the engine."""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )


@asynccontextmanager
async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations."""
    session = sessionmaker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
