"""Comment service."""
from __future__ import annotations

from app.core.constants import COMMENT_MAX_LENGTH
from app.core.logging import get_logger
from app.db.models import Comment, Role, Task, User
from app.repositories import CommentRepository

logger = get_logger(__name__)


class CommentServiceError(Exception):
    """Domain-level error in :class:`CommentService`."""


class CommentService:
    """Encapsulates comment creation and listing rules."""

    def __init__(self, repo: CommentRepository) -> None:
        self._repo = repo

    @staticmethod
    def _validate(text: str) -> str:
        text = text.strip()
        if not text:
            raise CommentServiceError("Комментарий не может быть пустым.")
        if len(text) > COMMENT_MAX_LENGTH:
            raise CommentServiceError(
                f"Комментарий не может быть длиннее {COMMENT_MAX_LENGTH} символов."
            )
        return text

    @staticmethod
    def can_comment(task: Task, user: User) -> bool:
        if user.role == Role.ADMIN:
            return True
        if user.role == Role.CUSTOMER and task.customer_id == user.id:
            return True
        if user.role == Role.DESIGNER and task.designer_id == user.id:
            return True
        return False

    async def add(self, *, task: Task, author: User, text: str) -> Comment:
        if not self.can_comment(task, author):
            raise CommentServiceError("У вас нет прав комментировать эту задачу.")
        text = self._validate(text)
        comment = await self._repo.add(
            task_id=task.id,
            author_id=author.id,
            author_role=author.role,
            text=text,
        )
        logger.info(
            "Comment added",
            task_id=task.id,
            comment_id=comment.id,
            role=author.role.value,
        )
        return comment

    async def list_for_task(self, task_id: int) -> list[Comment]:
        return await self._repo.list_for_task(task_id)
