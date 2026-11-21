"""FSM states for task creation and attachment flows."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class NewTaskStates(StatesGroup):
    """Fast task-creation flow.

    Three steps only:

    1. ``title``        — task title (single text message)
    2. ``description``  — description **and** any files in one go;
       the user keeps sending text/photos/documents until they press
       "Далее"
    3. ``designer``     — pick an assignee (or "Without assignment");
       picking creates the task immediately, no separate confirmation
       step

    Priority defaults to ``MEDIUM`` and deadline is left empty; both
    can be tweaked later from the task card.
    """

    title = State()
    description = State()
    designer = State()


class AttachFileStates(StatesGroup):
    """Adding files to an existing task."""

    waiting_files = State()


class TaskFocus(StatesGroup):
    """User has an "active task" open — any plain message in this
    state is automatically routed to that task (text → comment,
    document/photo → attachment).

    The active task id is stored in the FSM data under
    ``active_task_id``.
    """

    active = State()


class EditTaskStates(StatesGroup):
    """Editing fields of an existing task.

    All three states stash the target task id in FSM data under
    ``task_id``.  Priority is *not* here — it's a one-shot inline
    picker without any text input.
    """

    title = State()
    description = State()
    deadline = State()
