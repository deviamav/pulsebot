"""Comment repository."""
from __future__ import annotations

from sqlalchemy import select

from app.db.models import Comment, Role
from app.repositories.base import BaseRepository


class CommentRepository(BaseRepository):
    """Persistence operations for comments."""

    async def add(
        self, *, task_id: int, author_id: int, author_role: Role, text: str
    ) -> Comment:
        comment = Comment(
            task_id=task_id,
            author_id=author_id,
            author_role=author_role,
            text=text,
        )
        self.session.add(comment)
        await self.session.flush()
        return comment

    async def list_for_task(self, task_id: int) -> list[Comment]:
        stmt = (
            select(Comment)
            .where(Comment.task_id == task_id)
            .order_by(Comment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
