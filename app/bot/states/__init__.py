"""FSM state groups."""
from app.bot.states.admin import AdminAssignRole, AdminRenameUser
from app.bot.states.comment import CommentStates
from app.bot.states.invite import CreateInviteStates, InviteRedeemStates
from app.bot.states.task import (
    AttachFileStates,
    EditTaskStates,
    NewTaskStates,
    TaskFocus,
)

__all__ = [
    "AdminAssignRole",
    "AdminRenameUser",
    "AttachFileStates",
    "CommentStates",
    "CreateInviteStates",
    "EditTaskStates",
    "InviteRedeemStates",
    "NewTaskStates",
    "TaskFocus",
]
