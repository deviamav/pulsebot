"""Inline keyboards and CallbackData factories."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Priority, Role, TaskStatus, User


# -------- callback data classes --------


class PageCallback(CallbackData, prefix="pg"):
    """Pagination navigation between task pages."""

    scope: str  # "my", "active", "finished", "new", "inprog", "all"
    page: int


class TaskActionCallback(CallbackData, prefix="task"):
    """Open a task or perform an action."""

    action: Literal[
        "open",
        "status",
        "comment",
        "attach",
        "close",
        "back",
        "edit",
        "delete",
    ]
    task_id: int


class TaskEditCallback(CallbackData, prefix="tedit"):
    """Pick a field to edit on an existing task."""

    field: Literal["title", "description", "priority", "deadline"]
    task_id: int


class TaskPriorityCallback(CallbackData, prefix="tprio"):
    """Set a new priority on an existing task (admin/customer)."""

    task_id: int
    value: str


class TaskDeadlineCallback(CallbackData, prefix="tddl"):
    """Set or clear a deadline on an existing task.

    ``preset`` values:
    * ``today``    — today 18:00 UTC
    * ``tomorrow`` — tomorrow 18:00 UTC
    * ``plus3``    — now + 3 days, 18:00 UTC
    * ``plus7``    — now + 7 days, 18:00 UTC
    * ``clear``    — remove the deadline
    * ``manual``   — open an FSM input for a custom value
    """

    task_id: int
    preset: Literal["today", "tomorrow", "plus3", "plus7", "clear", "manual"]


class StatusChangeCallback(CallbackData, prefix="status"):
    """Change task status."""

    task_id: int
    status: str


class PriorityCallback(CallbackData, prefix="prio"):
    """Pick a priority during task creation."""

    value: str


class NewTaskCallback(CallbackData, prefix="nt"):
    """Navigation buttons during the fast new-task FSM."""

    action: Literal[
        "next",
        "skip_designer",
        "auto_designer",
        "cancel",
        "back",
    ]


class DesignerPickerCallback(CallbackData, prefix="dp"):
    """Pick a designer either while creating or reassigning a task."""

    designer_id: int
    scope: Literal["new", "reassign"]
    task_id: int = 0


class AdminTaskCallback(CallbackData, prefix="admin"):
    """Admin-only actions on a task."""

    action: Literal["reassign", "close"]
    task_id: int


class RolePickerCallback(CallbackData, prefix="role"):
    role: str


class UserAdminCallback(CallbackData, prefix="user"):
    """Admin-only inline action on a specific user row."""

    action: Literal[
        "open",
        "rename",
        "block",
        "unblock",
        "delete",
        "back",
    ]
    user_id: int


class ConfirmCallback(CallbackData, prefix="cfm"):
    """Generic two-step confirmation factory."""

    action: str  # arbitrary action identifier ("close_task", "revoke_invite", "ban_user")
    target_id: int
    yes: bool


class InviteMenuCallback(CallbackData, prefix="inv"):
    """Top-level invites submenu."""

    action: Literal["create", "list", "close"]


class InviteRoleCallback(CallbackData, prefix="invr"):
    role: str


class InviteTtlCallback(CallbackData, prefix="invt"):
    ttl: str  # "1d", "7d", "30d", "inf"


class InviteCountCallback(CallbackData, prefix="invc"):
    """Number of invite codes to create in one go."""

    count: int


# -------- builders --------


def priority_keyboard() -> InlineKeyboardMarkup:
    """Standalone priority picker used from the task card.

    The fast new-task flow no longer asks for priority during
    creation — Medium is assumed and can be changed afterwards through
    this keyboard.
    """
    builder = InlineKeyboardBuilder()
    for prio in Priority:
        builder.button(
            text=prio.label,
            callback_data=PriorityCallback(value=prio.value).pack(),
        )
    builder.adjust(3)
    return builder.as_markup()


def designer_picker_keyboard(
    designers: Iterable[User],
    *,
    scope: Literal["new", "reassign"] = "new",
    task_id: int = 0,
    include_skip: bool = False,
    include_auto: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if include_auto and scope == "new":
        builder.row(
            InlineKeyboardButton(
                text="✨ Авто (наименее загруженный)",
                callback_data=NewTaskCallback(action="auto_designer").pack(),
            )
        )
    for designer in designers:
        builder.button(
            text=designer.full_name,
            callback_data=DesignerPickerCallback(
                designer_id=designer.id, scope=scope, task_id=task_id
            ).pack(),
        )
    builder.adjust(1)
    if include_skip and scope == "new":
        builder.row(
            InlineKeyboardButton(
                text="Без назначения",
                callback_data=NewTaskCallback(action="skip_designer").pack(),
            )
        )
    if scope == "new":
        builder.row(
            InlineKeyboardButton(
                text="« Назад",
                callback_data=NewTaskCallback(action="back").pack(),
            ),
            InlineKeyboardButton(
                text="Отмена",
                callback_data=NewTaskCallback(action="cancel").pack(),
            ),
        )
    return builder.as_markup()


def new_task_description_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown during the "description + files" step.

    The user keeps sending text and/or attachments; once happy they
    press "➡️ Далее" to move on to the designer picker.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➡️ Далее",
            callback_data=NewTaskCallback(action="next").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=NewTaskCallback(action="cancel").pack(),
        ),
    )
    return builder.as_markup()


# Friendlier button labels for status transitions: instead of generic
# "➜ {status}" we describe the *intent* of the transition. Anything not
# listed here falls back to the generic label.
_TRANSITION_LABELS: dict[tuple[TaskStatus, TaskStatus], str] = {
    (TaskStatus.NEW, TaskStatus.IN_PROGRESS): "▶️ Взять в работу",
    (TaskStatus.IN_PROGRESS, TaskStatus.WAITING_REVIEW): "🔎 На проверку",
    (TaskStatus.NEEDS_REVISION, TaskStatus.IN_PROGRESS): "▶️ Снова в работу",
    (TaskStatus.WAITING_REVIEW, TaskStatus.DONE): "✅ Принять",
    (TaskStatus.WAITING_REVIEW, TaskStatus.NEEDS_REVISION): "✏️ Нужны правки",
}


def _transition_label(from_status: TaskStatus, to_status: TaskStatus) -> str:
    label = _TRANSITION_LABELS.get((from_status, to_status))
    return label if label is not None else f"➜ {to_status.label}"


def task_card_keyboard(
    *,
    task_id: int,
    viewer_role: Role,
    status: TaskStatus,
    is_assigned: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Status transitions are filtered server-side; here we just show the buttons
    # that are normally available for the role.
    available: list[TaskStatus] = []
    if viewer_role == Role.DESIGNER and is_assigned:
        if status == TaskStatus.NEW:
            available.append(TaskStatus.IN_PROGRESS)
        elif status == TaskStatus.IN_PROGRESS:
            available.append(TaskStatus.WAITING_REVIEW)
        elif status == TaskStatus.NEEDS_REVISION:
            available.append(TaskStatus.IN_PROGRESS)
    elif viewer_role == Role.CUSTOMER:
        if status == TaskStatus.WAITING_REVIEW:
            available.extend([TaskStatus.DONE, TaskStatus.NEEDS_REVISION])
    elif viewer_role == Role.ADMIN:
        for st in TaskStatus:
            if st != status:
                available.append(st)

    for st in available:
        builder.button(
            text=_transition_label(status, st),
            callback_data=StatusChangeCallback(task_id=task_id, status=st.value).pack(),
        )
    builder.adjust(2)

    builder.row(
        InlineKeyboardButton(
            text="💬 Комментарий",
            callback_data=TaskActionCallback(action="comment", task_id=task_id).pack(),
        ),
        InlineKeyboardButton(
            text="📎 Файл",
            callback_data=TaskActionCallback(action="attach", task_id=task_id).pack(),
        ),
    )

    # Owner-side actions: editing & deletion. Designers don't get
    # these — they collaborate via status changes / comments.
    if viewer_role in (Role.CUSTOMER, Role.ADMIN):
        builder.row(
            InlineKeyboardButton(
                text="✏️ Изменить",
                callback_data=TaskActionCallback(
                    action="edit", task_id=task_id
                ).pack(),
            ),
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=TaskActionCallback(
                    action="delete", task_id=task_id
                ).pack(),
            ),
        )

    if viewer_role == Role.ADMIN:
        builder.row(
            InlineKeyboardButton(
                text="Переназначить",
                callback_data=AdminTaskCallback(
                    action="reassign", task_id=task_id
                ).pack(),
            )
        )

    builder.row(
        InlineKeyboardButton(
            text="« Назад",
            callback_data=TaskActionCallback(action="back", task_id=task_id).pack(),
        )
    )
    return builder.as_markup()


def task_edit_menu_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Sub-menu shown after the user taps "✏️ Изменить" on a task card."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📝 Название",
            callback_data=TaskEditCallback(field="title", task_id=task_id).pack(),
        ),
        InlineKeyboardButton(
            text="📄 Описание",
            callback_data=TaskEditCallback(field="description", task_id=task_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🎯 Приоритет",
            callback_data=TaskEditCallback(field="priority", task_id=task_id).pack(),
        ),
        InlineKeyboardButton(
            text="📅 Дедлайн",
            callback_data=TaskEditCallback(field="deadline", task_id=task_id).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="« К карточке",
            callback_data=TaskActionCallback(
                action="open", task_id=task_id
            ).pack(),
        ),
    )
    return builder.as_markup()


def task_priority_picker(task_id: int) -> InlineKeyboardMarkup:
    """Standalone priority picker bound to an existing task."""
    builder = InlineKeyboardBuilder()
    for prio in Priority:
        builder.button(
            text=prio.label,
            callback_data=TaskPriorityCallback(
                task_id=task_id, value=prio.value
            ).pack(),
        )
    builder.adjust(3)
    builder.row(
        InlineKeyboardButton(
            text="« Назад",
            callback_data=TaskActionCallback(
                action="edit", task_id=task_id
            ).pack(),
        ),
    )
    return builder.as_markup()


def task_deadline_picker(task_id: int) -> InlineKeyboardMarkup:
    """Preset-based deadline picker bound to an existing task."""
    builder = InlineKeyboardBuilder()
    presets: tuple[tuple[str, str], ...] = (
        ("today", "Сегодня 18:00"),
        ("tomorrow", "Завтра 18:00"),
        ("plus3", "+3 дня"),
        ("plus7", "+7 дней"),
    )
    for preset, label in presets:
        builder.button(
            text=label,
            callback_data=TaskDeadlineCallback(
                task_id=task_id, preset=preset
            ).pack(),
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text="✍️ Ввести вручную",
            callback_data=TaskDeadlineCallback(
                task_id=task_id, preset="manual"
            ).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🚫 Без дедлайна",
            callback_data=TaskDeadlineCallback(
                task_id=task_id, preset="clear"
            ).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="« Назад",
            callback_data=TaskActionCallback(
                action="edit", task_id=task_id
            ).pack(),
        ),
    )
    return builder.as_markup()


def status_keyboard(task_id: int, allowed: Iterable[TaskStatus]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for st in allowed:
        builder.button(
            text=st.label,
            callback_data=StatusChangeCallback(task_id=task_id, status=st.value).pack(),
        )
    builder.adjust(2)
    return builder.as_markup()


def pagination_keyboard(
    *,
    scope: str,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_prev:
        builder.button(
            text="«",
            callback_data=PageCallback(scope=scope, page=page - 1).pack(),
        )
    builder.button(text=f"стр. {page + 1}", callback_data="noop")
    if has_next:
        builder.button(
            text="»",
            callback_data=PageCallback(scope=scope, page=page + 1).pack(),
        )
    builder.adjust(3)
    return builder.as_markup()


def role_picker_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for role in (Role.CUSTOMER, Role.DESIGNER, Role.ADMIN):
        builder.button(
            text=role.label,
            callback_data=RolePickerCallback(role=role.value).pack(),
        )
    builder.adjust(3)
    return builder.as_markup()


def admin_assign_role_keyboard() -> InlineKeyboardMarkup:
    return role_picker_keyboard()


# -------- confirmations --------


def confirm_keyboard(
    *,
    action: str,
    target_id: int,
    yes_text: str = "✅ Да",
    no_text: str = "❌ Нет",
) -> InlineKeyboardMarkup:
    """Build a two-button confirmation keyboard.

    The handler receives :class:`ConfirmCallback` with ``yes`` flag.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=yes_text,
        callback_data=ConfirmCallback(
            action=action, target_id=target_id, yes=True
        ).pack(),
    )
    builder.button(
        text=no_text,
        callback_data=ConfirmCallback(
            action=action, target_id=target_id, yes=False
        ).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


# -------- invites --------


def invites_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Создать инвайт",
        callback_data=InviteMenuCallback(action="create").pack(),
    )
    builder.button(
        text="📜 Активные инвайты",
        callback_data=InviteMenuCallback(action="list").pack(),
    )
    builder.button(
        text="✖ Закрыть",
        callback_data=InviteMenuCallback(action="close").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def invite_role_picker() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Заказчик",
        callback_data=InviteRoleCallback(role=Role.CUSTOMER.value).pack(),
    )
    builder.button(
        text="Дизайнер",
        callback_data=InviteRoleCallback(role=Role.DESIGNER.value).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def invite_ttl_picker() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ttl, label in (
        ("1d", "1 день"),
        ("7d", "7 дней"),
        ("30d", "30 дней"),
        ("inf", "Без ограничения"),
    ):
        builder.button(
            text=label, callback_data=InviteTtlCallback(ttl=ttl).pack()
        )
    builder.adjust(2)
    return builder.as_markup()


def users_admin_keyboard(users: Iterable[User]) -> InlineKeyboardMarkup:
    """Per-user buttons that open the user-management card."""
    builder = InlineKeyboardBuilder()
    for u in users:
        flag = "" if u.is_active else " 🚫"
        builder.button(
            text=f"#{u.id} {u.full_name}{flag}",
            callback_data=UserAdminCallback(
                action="open", user_id=u.id
            ).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


def user_delete_choice_keyboard(target_id: int) -> InlineKeyboardMarkup:
    """Three-way picker shown when deleting a designer with active load.

    The admin chooses whether the active tasks should be migrated to
    the rest of the team or simply unlinked (left without an assignee).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔄 Перераспределить и удалить",
            callback_data=ConfirmCallback(
                action="del_user_dist", target_id=target_id, yes=True
            ).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✂️ Удалить, оставив задачи без исполнителя",
            callback_data=ConfirmCallback(
                action="del_user_drop", target_id=target_id, yes=True
            ).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="« Отмена",
            callback_data=UserAdminCallback(
                action="open", user_id=target_id
            ).pack(),
        )
    )
    return builder.as_markup()


def user_card_admin_keyboard(target: User) -> InlineKeyboardMarkup:
    """Admin actions available on a user-management card."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ Переименовать",
            callback_data=UserAdminCallback(
                action="rename", user_id=target.id
            ).pack(),
        ),
    )
    if target.is_active:
        builder.row(
            InlineKeyboardButton(
                text="🚫 Заблокировать",
                callback_data=UserAdminCallback(
                    action="block", user_id=target.id
                ).pack(),
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="✅ Разблокировать",
                callback_data=UserAdminCallback(
                    action="unblock", user_id=target.id
                ).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=UserAdminCallback(
                action="delete", user_id=target.id
            ).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="« К списку",
            callback_data=UserAdminCallback(
                action="back", user_id=target.id
            ).pack(),
        ),
    )
    return builder.as_markup()


def invite_count_picker() -> InlineKeyboardMarkup:
    """Choose how many invite codes to create at once."""
    builder = InlineKeyboardBuilder()
    for count, label in (
        (1, "1 код"),
        (3, "3 кода"),
        (5, "5 кодов"),
        (10, "10 кодов"),
    ):
        builder.button(
            text=label,
            callback_data=InviteCountCallback(count=count).pack(),
        )
    builder.adjust(2)
    return builder.as_markup()


def invite_item_keyboard(invite_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Отозвать",
        callback_data=ConfirmCallback(
            action="revoke_invite", target_id=invite_id, yes=False
        ).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()
