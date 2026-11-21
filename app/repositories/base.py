"""Base repository providing a session reference."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Common base for repositories holding the async session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
