"""Attachment service."""
from __future__ import annotations

from app.core.logging import get_logger
from app.db.models import Attachment, Role, Task, User
from app.repositories import AttachmentRepository

logger = get_logger(__name__)


class AttachmentServiceError(Exception):
    """Domain-level error in :class:`AttachmentService`."""


SUPPORTED_MIME_HINTS: tuple[str, ...] = (
    "image/",
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
    "application/vnd.adobe.photoshop",
    "image/vnd.adobe.photoshop",
)


class AttachmentService:
    """Persists Telegram-hosted attachments tied to tasks."""

    def __init__(self, repo: AttachmentRepository) -> None:
        self._repo = repo

    @staticmethod
    def can_attach(task: Task, user: User) -> bool:
        if user.role == Role.ADMIN:
            return True
        if user.role == Role.CUSTOMER and task.customer_id == user.id:
            return True
        if user.role == Role.DESIGNER and task.designer_id == user.id:
            return True
        return False

    async def add(
        self,
        *,
        task: Task,
        uploader: User,
        telegram_file_id: str,
        media_type: str,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_unique_id: str | None = None,
    ) -> Attachment:
        if not self.can_attach(task, uploader):
            raise AttachmentServiceError(
                "У вас нет прав прикреплять файлы к этой задаче."
            )
        attachment = await self._repo.add(
            task_id=task.id,
            telegram_file_id=telegram_file_id,
            media_type=media_type,
            uploaded_by=uploader.id,
            file_name=file_name,
            mime_type=mime_type,
            file_unique_id=file_unique_id,
        )
        logger.info(
            "Attachment added",
            task_id=task.id,
            attachment_id=attachment.id,
            media_type=media_type,
        )
        return attachment

    async def list_for_task(self, task_id: int) -> list[Attachment]:
        return await self._repo.list_for_task(task_id)
