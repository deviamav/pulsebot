"""Invite code service: creation, validation, redemption."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.db.models import InviteCode, Role, User
from app.repositories import InviteCodeRepository, UserRepository
from app.utils.datetime import utcnow

logger = get_logger(__name__)

# Strict allow-list to prevent injecting non-printable / control chars
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Hard cap on bulk creation to prevent accidental flooding of the DB.
MAX_BULK_INVITES = 20


class InviteServiceError(Exception):
    """Domain-level error in :class:`InviteService`."""


class InviteService:
    """Encapsulates invite-code lifecycle."""

    def __init__(
        self,
        invite_repo: InviteCodeRepository,
        user_repo: UserRepository,
    ) -> None:
        self._invites = invite_repo
        self._users = user_repo

    @staticmethod
    def _generate_code() -> str:
        return secrets.token_urlsafe(12).replace("=", "").rstrip("-_")[:16]

    @staticmethod
    def normalize_code(raw: str) -> str:
        """Trim and check the format of an externally-supplied code."""
        candidate = (raw or "").strip()
        if not _CODE_PATTERN.match(candidate):
            raise InviteServiceError("Неверный формат инвайт-кода.")
        return candidate

    async def create_invite(
        self,
        *,
        creator: User,
        role: Role,
        ttl: timedelta | None,
        note: str | None = None,
    ) -> InviteCode:
        if creator.role != Role.ADMIN:
            raise InviteServiceError("Создавать инвайты может только админ.")
        if role == Role.ADMIN:
            raise InviteServiceError(
                "Нельзя выдавать инвайт-код на роль ADMIN."
            )

        expires_at = utcnow() + ttl if ttl else None

        for _ in range(5):
            code = self._generate_code()
            existing = await self._invites.get_by_code(code)
            if existing is None:
                break
        else:
            raise InviteServiceError("Не удалось сгенерировать уникальный код.")

        invite = await self._invites.create(
            code=code,
            role=role,
            created_by_id=creator.id,
            expires_at=expires_at,
            note=note,
        )
        logger.info(
            "Invite created",
            invite_id=invite.id,
            role=role.value,
            creator_id=creator.id,
            ttl_seconds=int(ttl.total_seconds()) if ttl else None,
        )
        return invite

    async def create_invites_bulk(
        self,
        *,
        creator: User,
        role: Role,
        ttl: timedelta | None,
        count: int,
        note: str | None = None,
    ) -> list[InviteCode]:
        """Create ``count`` invite codes for the same role/TTL in one go.

        Used by the admin "create N invites" flow. All invites share the
        same role, TTL and creator. The DB session is committed by the
        caller (middleware), so all inserts succeed or fail together.
        """
        if count < 1 or count > MAX_BULK_INVITES:
            raise InviteServiceError(
                f"Количество должно быть от 1 до {MAX_BULK_INVITES}."
            )
        invites: list[InviteCode] = []
        for _ in range(count):
            invite = await self.create_invite(
                creator=creator, role=role, ttl=ttl, note=note
            )
            invites.append(invite)
        logger.info(
            "Invites bulk-created",
            count=len(invites),
            role=role.value,
            creator_id=creator.id,
        )
        return invites

    async def validate(self, code: str) -> InviteCode:
        """Return the invite if it can be redeemed, raise otherwise."""
        code = self.normalize_code(code)
        invite = await self._invites.get_by_code(code)
        if invite is None:
            raise InviteServiceError("Инвайт-код не найден.")
        if not invite.is_usable(now=utcnow()):
            if invite.is_revoked:
                raise InviteServiceError("Инвайт-код отозван.")
            if invite.used_by_id is not None:
                raise InviteServiceError("Инвайт-код уже использован.")
            raise InviteServiceError("Срок действия инвайт-кода истёк.")
        return invite

    async def redeem(
        self, *, code: str, telegram_id: int, full_name: str
    ) -> User:
        """Consume the invite and create or activate a user."""
        invite = await self.validate(code)

        existing = await self._users.get_by_telegram_id(telegram_id)
        if existing is not None and existing.is_active:
            raise InviteServiceError(
                "Вы уже зарегистрированы. Инвайт-код не нужен."
            )

        if existing is not None:
            existing.role = invite.role
            existing.full_name = full_name
            existing.is_active = True
            user = existing
        else:
            user = await self._users.create(
                telegram_id=telegram_id,
                role=invite.role,
                full_name=full_name,
            )

        await self._invites.mark_used(
            invite.id, used_by_id=user.id, used_at=utcnow()
        )

        logger.info(
            "Invite redeemed",
            invite_id=invite.id,
            user_id=user.id,
            role=invite.role.value,
        )
        return user

    async def revoke(self, *, invite_id: int, actor: User) -> InviteCode:
        if actor.role != Role.ADMIN:
            raise InviteServiceError("Отзывать инвайты может только админ.")
        invite = await self._invites.revoke(invite_id)
        if invite is None:
            raise InviteServiceError("Инвайт не найден.")
        logger.info(
            "Invite revoked", invite_id=invite.id, actor_id=actor.id
        )
        return invite

    async def list_active(self) -> list[InviteCode]:
        return await self._invites.list_active()

    async def get(self, invite_id: int) -> InviteCode | None:
        return await self._invites.get_by_id(invite_id)


def parse_ttl(value: str) -> timedelta | None:
    """Parse a TTL token sent in callback data.

    Supported tokens: ``1d``, ``7d``, ``30d``, ``inf``.
    """
    if value == "inf":
        return None
    if value.endswith("d") and value[:-1].isdigit():
        return timedelta(days=int(value[:-1]))
    if value.endswith("h") and value[:-1].isdigit():
        return timedelta(hours=int(value[:-1]))
    raise InviteServiceError(f"Неизвестный TTL: {value}")


__all__ = ["InviteService", "InviteServiceError", "parse_ttl"]
