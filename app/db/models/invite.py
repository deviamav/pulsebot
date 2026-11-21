"""Invite code ORM model — single-use signup tokens issued by admins."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.enums import Role

if TYPE_CHECKING:
    from app.db.models.user import User


class InviteCode(Base, TimestampMixin):
    """A single-use invite token authorising a user to register with a role."""

    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="user_role", native_enum=False, length=32),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])
    used_by: Mapped["User | None"] = relationship("User", foreign_keys=[used_by_id])

    def is_usable(self, *, now: datetime) -> bool:
        if self.is_revoked:
            return False
        if self.used_by_id is not None:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True

    def __repr__(self) -> str:
        return (
            f"<InviteCode id={self.id} role={self.role.value} "
            f"revoked={self.is_revoked} used={self.used_by_id is not None}>"
        )
