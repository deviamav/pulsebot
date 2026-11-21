"""Authentication / user-resolution middleware."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.core.logging import get_logger
from app.services import UserService

logger = get_logger(__name__)


def _extract_user(event: TelegramObject) -> tuple[int, str] | None:
    tg_user = None
    if isinstance(event, Update):
        if event.message:
            tg_user = event.message.from_user
        elif event.callback_query:
            tg_user = event.callback_query.from_user
        elif event.edited_message:
            tg_user = event.edited_message.from_user
    elif isinstance(event, Message):
        tg_user = event.from_user
    elif isinstance(event, CallbackQuery):
        tg_user = event.from_user

    if tg_user is None or tg_user.is_bot:
        return None

    full_name = tg_user.full_name or str(tg_user.id)
    return tg_user.id, full_name


class AuthMiddleware(BaseMiddleware):
    """Resolve user from DB and inject into handler context.

    Unknown users are blocked except for statically-configured admins.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_service: UserService | None = data.get("user_service")
        if user_service is None:
            return await handler(event, data)

        extracted = _extract_user(event)
        if extracted is None:
            return await handler(event, data)

        telegram_id, full_name = extracted
        user = await user_service.get_or_bootstrap_admin(
            telegram_id=telegram_id, full_name=full_name
        )

        data["user"] = user
        data["telegram_id"] = telegram_id
        return await handler(event, data)
