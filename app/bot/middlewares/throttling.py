"""Per-user rate limiting based on Redis."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Reject events that exceed the configured per-user rate.

    Uses Redis ``SET key value EX ttl NX`` semantics: while the key exists
    the user is considered to be in a cool-down window.
    """

    def __init__(self, *, redis: Redis, rate_per_second: float) -> None:
        self._redis = redis
        # Window length in milliseconds (1 / rate)
        self._window_ms = max(100, int(1000 / max(rate_per_second, 0.1)))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_id = data.get("telegram_id")
        if telegram_id is None:
            return await handler(event, data)

        key = f"throttle:{telegram_id}"
        ok = await self._redis.set(
            name=key, value=b"1", px=self._window_ms, nx=True
        )
        if not ok:
            if isinstance(event, Message):
                try:
                    await event.answer("Занадто швидко. Будь ласка, зачекайте секунду.")
                except Exception:
                    pass
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("Зачекайте секунду…", show_alert=False)
                except Exception:
                    pass
            return None

        return await handler(event, data)
