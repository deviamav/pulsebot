"""DB session injection middleware + service factory."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.repositories import (
    AttachmentRepository,
    CommentRepository,
    InviteCodeRepository,
    TaskRepository,
    UserRepository,
)
from app.services import (
    AttachmentService,
    CommentService,
    InviteService,
    TaskService,
    UserService,
)

logger = get_logger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Open an async session per update and inject repositories/services.

    The session is committed on successful handler completion and rolled back
    on exceptions.
    """

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        admin_ids: list[int],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession = self._sessionmaker()
        try:
            user_repo = UserRepository(session)
            task_repo = TaskRepository(session)
            comment_repo = CommentRepository(session)
            attachment_repo = AttachmentRepository(session)
            invite_repo = InviteCodeRepository(session)

            data.update(
                {
                    "session": session,
                    "user_repo": user_repo,
                    "task_repo": task_repo,
                    "comment_repo": comment_repo,
                    "attachment_repo": attachment_repo,
                    "invite_repo": invite_repo,
                    "user_service": UserService(
                        user_repo, admin_ids=self._admin_ids
                    ),
                    "task_service": TaskService(task_repo),
                    "comment_service": CommentService(comment_repo),
                    "attachment_service": AttachmentService(attachment_repo),
                    "invite_service": InviteService(invite_repo, user_repo),
                }
            )

            result = await handler(event, data)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
