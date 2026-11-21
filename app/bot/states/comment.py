"""FSM states for adding comments."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CommentStates(StatesGroup):
    waiting_text = State()
