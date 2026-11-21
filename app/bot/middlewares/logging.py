"""Bind a per-update structlog context."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update


class StructlogContextMiddleware(BaseMiddleware):
    """Attach contextual fields to every log emitted while handling an update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: dict[str, Any] = {}
        update_id: int | None = None
        telegram_id: int | None = None
        event_kind: str | None = None

        if isinstance(event, Update):
            update_id = event.update_id
            if event.message:
                telegram_id = event.message.from_user.id if event.message.from_user else None
                event_kind = "message"
            elif event.callback_query:
                telegram_id = event.callback_query.from_user.id
                event_kind = "callback"
        elif isinstance(event, Message):
            telegram_id = event.from_user.id if event.from_user else None
            event_kind = "message"
        elif isinstance(event, CallbackQuery):
            telegram_id = event.from_user.id
            event_kind = "callback"

        if update_id is not None:
            ctx["update_id"] = update_id
        if telegram_id is not None:
            ctx["telegram_id"] = telegram_id
        if event_kind is not None:
            ctx["event"] = event_kind

        with structlog.contextvars.bound_contextvars(**ctx):
            return await handler(event, data)
