"""Middleware that auto-exits the "active task" focus mode.

Whenever the user has an open task card (``TaskFocus.active``) any plain
text or file is routed straight into that task — see the handlers in
``app.bot.handlers.tasks``.

The natural way to *leave* that mode is to either tap "« Назад" on the
card, run ``/cancel`` / ``/menu``, or simply press one of the main-menu
reply-keyboard buttons.  This middleware handles the latter case: if it
sees an incoming :class:`~aiogram.types.Message` that is a known menu
button label *or* a slash-command and the user is currently focused on
a task, it clears the FSM state before the handler runs.  Without that
the next free-form message would be silently captured into the old task
which is confusing.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from app.bot.keyboards.reply import ALL_MENU_BUTTONS
from app.bot.states import TaskFocus


class TaskFocusGuardMiddleware(BaseMiddleware):
    """Drop ``TaskFocus.active`` when the user navigates away via menu."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            state: FSMContext | None = data.get("state")
            if state is not None:
                text = event.text.strip()
                is_command = text.startswith("/")
                is_menu_btn = text in ALL_MENU_BUTTONS
                if is_command or is_menu_btn:
                    current = await state.get_state()
                    if current == TaskFocus.active.state:
                        await state.clear()
        return await handler(event, data)
