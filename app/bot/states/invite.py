"""FSM states for invite flows."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class InviteRedeemStates(StatesGroup):
    """Unauthenticated user redeems an invite code and registers."""

    waiting_code = State()
    waiting_name = State()


class CreateInviteStates(StatesGroup):
    """Admin creates one or more new invite codes."""

    role = State()
    ttl = State()
    count = State()
