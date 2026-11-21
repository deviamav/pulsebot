"""FSM states for administrative flows."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminAssignRole(StatesGroup):
    """Adding/updating a user role by Telegram ID."""

    telegram_id = State()
    full_name = State()
    role = State()


class AdminRenameUser(StatesGroup):
    """Admin renames an existing user — target id is stored in FSM
    data under ``user_id``."""

    waiting_name = State()
