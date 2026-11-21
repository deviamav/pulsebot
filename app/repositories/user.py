"""User repository."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import Attachment, Comment, Role, Task, User
from app.repositories.base import BaseRepository


@dataclass(slots=True)
class UserDependencies:
    """How a user is referenced from other tables.

    Used to decide whether a hard-delete is safe and what to show
    in the confirmation prompt.
    """

    tasks_as_customer: int = 0
    tasks_as_designer: int = 0
    comments: int = 0
    attachments: int = 0

    @property
    def total(self) -> int:
        return (
            self.tasks_as_customer
            + self.tasks_as_designer
            + self.comments
            + self.attachments
        )


class UserRepository(BaseRepository):
    """Read/write operations for :class:`User`."""

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def create(
        self, *, telegram_id: int, role: Role, full_name: str
    ) -> User:
        user = User(telegram_id=telegram_id, role=role, full_name=full_name)
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_telegram_id(telegram_id)
            assert existing is not None
            return existing
        return user

    async def upsert_role(
        self, *, telegram_id: int, role: Role, full_name: str
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            return await self.create(
                telegram_id=telegram_id, role=role, full_name=full_name
            )
        user.role = role
        user.full_name = full_name
        user.is_active = True
        await self.session.flush()
        return user

    async def rename(self, user_id: int, *, full_name: str) -> User | None:
        """Update display name only — does not touch the role or
        active flag.  Returns the refreshed row or ``None`` if the
        user is missing."""
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.full_name = full_name
        await self.session.flush()
        return user

    async def set_active(self, user_id: int, *, is_active: bool) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(is_active=is_active)
        )
        await self.session.execute(stmt)

    async def list_by_role(self, role: Role, *, active_only: bool = True) -> list[User]:
        stmt = select(User).where(User.role == role)
        if active_only:
            stmt = stmt.where(User.is_active.is_(True))
        stmt = stmt.order_by(User.full_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[User]:
        stmt = select(User).order_by(User.role, User.full_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_role(self) -> dict[Role, int]:
        stmt = select(User.role, func.count(User.id)).group_by(User.role)
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

    async def dependencies(self, user_id: int) -> UserDependencies:
        """Count rows that reference this user across the schema."""
        tasks_as_customer = (
            await self.session.execute(
                select(func.count(Task.id)).where(Task.customer_id == user_id)
            )
        ).scalar_one()
        tasks_as_designer = (
            await self.session.execute(
                select(func.count(Task.id)).where(Task.designer_id == user_id)
            )
        ).scalar_one()
        comments = (
            await self.session.execute(
                select(func.count(Comment.id)).where(Comment.author_id == user_id)
            )
        ).scalar_one()
        attachments = (
            await self.session.execute(
                select(func.count(Attachment.id)).where(
                    Attachment.uploaded_by == user_id
                )
            )
        ).scalar_one()
        return UserDependencies(
            tasks_as_customer=int(tasks_as_customer),
            tasks_as_designer=int(tasks_as_designer),
            comments=int(comments),
            attachments=int(attachments),
        )

    async def delete(self, user_id: int) -> bool:
        """Hard-delete a user.

        Caller must verify safety beforehand via :meth:`dependencies`:
        comments/attachments FKs use ``ON DELETE RESTRICT`` and would
        raise ``IntegrityError`` here.  We additionally pre-delete the
        user's own tasks as customer — their comments/attachments
        cascade away with them so the row can finally go.
        """
        await self.session.execute(
            delete(Task).where(Task.customer_id == user_id)
        )
        result = await self.session.execute(
            delete(User).where(User.id == user_id)
        )
        await self.session.flush()
        return bool(result.rowcount)
