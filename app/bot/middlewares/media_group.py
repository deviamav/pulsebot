"""Aggregate Telegram media groups into a single handler invocation.

Telegram delivers an "album" (several photos/documents sent at once) as
multiple separate ``Update``-s that share a common ``media_group_id``.
Without coordination this would trigger our handlers once per item and
produce a flood of confirmation messages ("Файл добавлен (1)", "(2)",
"(3)" …).

This middleware buffers messages that belong to the same album for a
short idle window and then dispatches **one** handler invocation,
passing the full list via ``data["album"]``.  Handlers may inspect that
key to decide whether to operate on a single message or on the whole
batch.

The implementation is intentionally tiny and dependency-free.  It is
not a hard guarantee — if Telegram delivers the items spaced wider than
``DEBOUNCE_SECONDS`` they will be processed separately, which is
acceptable degraded behaviour.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class MediaGroupMiddleware(BaseMiddleware):
    """Group messages by ``media_group_id`` and dispatch once."""

    DEBOUNCE_SECONDS: float = 0.8

    def __init__(self) -> None:
        self._batches: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        group_id = event.media_group_id
        batch = self._batches.setdefault(group_id, [])
        batch.append(event)

        # All but the first message in the group are swallowed; they
        # only contribute to the buffer above.
        if len(batch) > 1:
            return None

        # First message: wait briefly for siblings, then dispatch the
        # handler once with the full album.
        try:
            await asyncio.sleep(self.DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            self._batches.pop(group_id, None)
            raise

        album = self._batches.pop(group_id, [])
        if not album:
            return None

        data["album"] = album
        try:
            return await handler(album[0], data)
        finally:
            data.pop("album", None)
