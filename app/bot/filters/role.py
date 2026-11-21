"""Role-based access filter."""
from __future__ import annotations

from collections.abc import Iterable

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from app.db.models import Role, User


class RoleFilter(Filter):
    """Allow handler execution only for given user roles.

    Relies on the auth middleware which injects ``user`` into handler kwargs.
    """

    def __init__(self, *roles: Role) -> None:
        self.roles: tuple[Role, ...] = roles

    async def __call__(
        self,
        event: Message | CallbackQuery,
        **data: object,
    ) -> bool:
        user = data.get("user")
        if not isinstance(user, User):
            return False
        if not user.is_active:
            return False
        return user.role in self.roles

    @classmethod
    def admin(cls) -> RoleFilter:
        return cls(Role.ADMIN)

    @classmethod
    def customer(cls) -> RoleFilter:
        return cls(Role.CUSTOMER)

    @classmethod
    def designer(cls) -> RoleFilter:
        return cls(Role.DESIGNER)

    @classmethod
    def any_of(cls, roles: Iterable[Role]) -> RoleFilter:
        return cls(*roles)
