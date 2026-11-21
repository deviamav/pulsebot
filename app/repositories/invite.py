"""Invite code repository."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import InviteCode, Role
from app.repositories.base import BaseRepository


class InviteCodeRepository(BaseRepository):
    """Persistence operations for :class:`InviteCode`."""

    async def create(
        self,
        *,
        code: str,
        role: Role,
        created_by_id: int,
        expires_at: datetime | None,
        note: str | None = None,
    ) -> InviteCode:
        invite = InviteCode(
            code=code,
            role=role,
            created_by_id=created_by_id,
            expires_at=expires_at,
            note=note,
        )
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def get_by_code(self, code: str) -> InviteCode | None:
        stmt = (
            select(InviteCode)
            .where(InviteCode.code == code)
            .options(
                selectinload(InviteCode.created_by),
                selectinload(InviteCode.used_by),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, invite_id: int) -> InviteCode | None:
        stmt = (
            select(InviteCode)
            .where(InviteCode.id == invite_id)
            .options(
                selectinload(InviteCode.created_by),
                selectinload(InviteCode.used_by),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[InviteCode]:
        stmt = (
            select(InviteCode)
            .where(
                InviteCode.is_revoked.is_(False),
                InviteCode.used_by_id.is_(None),
            )
            .options(selectinload(InviteCode.created_by))
            .order_by(InviteCode.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, limit: int = 50) -> list[InviteCode]:
        stmt = (
            select(InviteCode)
            .options(
                selectinload(InviteCode.created_by),
                selectinload(InviteCode.used_by),
            )
            .order_by(InviteCode.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_used(
        self, invite_id: int, *, used_by_id: int, used_at: datetime
    ) -> InviteCode | None:
        invite = await self.session.get(InviteCode, invite_id)
        if invite is None:
            return None
        invite.used_by_id = used_by_id
        invite.used_at = used_at
        await self.session.flush()
        return invite

    async def revoke(self, invite_id: int) -> InviteCode | None:
        invite = await self.session.get(InviteCode, invite_id)
        if invite is None:
            return None
        invite.is_revoked = True
        await self.session.flush()
        return invite
