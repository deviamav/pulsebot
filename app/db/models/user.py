"""User ORM model."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.enums import Role

if TYPE_CHECKING:
    from app.db.models.task import Task


class User(Base, TimestampMixin):
    """A registered Telegram user with a system role."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="user_role", native_enum=False, length=32),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    customer_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="customer",
        foreign_keys="Task.customer_id",
        cascade="all, delete-orphan",
    )
    designer_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="designer",
        foreign_keys="Task.designer_id",
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} tg={self.telegram_id} role={self.role.value} "
            f"active={self.is_active}>"
        )
