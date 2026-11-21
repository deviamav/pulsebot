"""Attachment repository."""
from __future__ import annotations

from sqlalchemy import select

from app.db.models import Attachment
from app.repositories.base import BaseRepository


class AttachmentRepository(BaseRepository):
    """Persistence operations for attachments."""

    async def add(
        self,
        *,
        task_id: int,
        telegram_file_id: str,
        media_type: str,
        uploaded_by: int,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_unique_id: str | None = None,
    ) -> Attachment:
        attachment = Attachment(
            task_id=task_id,
            telegram_file_id=telegram_file_id,
            media_type=media_type,
            uploaded_by=uploaded_by,
            file_name=file_name,
            mime_type=mime_type,
            file_unique_id=file_unique_id,
        )
        self.session.add(attachment)
        await self.session.flush()
        return attachment

    async def list_for_task(self, task_id: int) -> list[Attachment]:
        stmt = (
            select(Attachment)
            .where(Attachment.task_id == task_id)
            .order_by(Attachment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
