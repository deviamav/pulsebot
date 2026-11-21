"""Administrative handlers."""
from __future__ import annotations

from html import escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import RoleFilter
from app.bot.keyboards import (
    AdminTaskCallback,
    ConfirmCallback,
    DesignerPickerCallback,
    InviteCountCallback,
    InviteMenuCallback,
    InviteRoleCallback,
    InviteTtlCallback,
    PageCallback,
    RolePickerCallback,
    TaskActionCallback,
    UserAdminCallback,
    admin_assign_role_keyboard,
    confirm_keyboard,
    designer_picker_keyboard,
    invite_count_picker,
    invite_role_picker,
    invite_ttl_picker,
    invites_menu_keyboard,
    main_menu,
    pagination_keyboard,
    user_card_admin_keyboard,
    user_delete_choice_keyboard,
    users_admin_keyboard,
)
from app.bot.keyboards.reply import (
    BTN_ALL_TASKS,
    BTN_ASSIGN_ROLE,
    BTN_INVITES,
    BTN_STATS,
    BTN_USERS,
)
from app.bot.states import AdminAssignRole, AdminRenameUser, CreateInviteStates
from app.bot.utils.formatting import format_task_short
from app.bot.utils.pagination import paginate_meta
from app.core.constants import DEFAULT_PAGE_SIZE
from app.db.models import Role, Task, TaskStatus, User
from app.repositories import TaskFilter
from app.services import InviteService, NotificationService, TaskService, UserService
from app.services.invite import InviteServiceError, parse_ttl
from app.services.task import TaskServiceError
from app.services.user import UserServiceError
from app.utils.datetime import format_dt

router = Router(name="admin")
router.message.filter(RoleFilter(Role.ADMIN))
router.callback_query.filter(RoleFilter(Role.ADMIN))


# ---------- All tasks ----------


@router.message(F.text == BTN_ALL_TASKS)
async def list_all(message: Message, user: User, task_service: TaskService) -> None:
    await _send(
        message,
        scope="a_all",
        flt=TaskFilter(),
        task_service=task_service,
        user=user,
    )


@router.callback_query(PageCallback.filter(F.scope == "a_all"))
async def paginate_all(
    cb: CallbackQuery,
    callback_data: PageCallback,
    user: User,
    task_service: TaskService,
) -> None:
    if isinstance(cb.message, Message):
        text, kb = await _render(
            scope="a_all",
            flt=TaskFilter(),
            task_service=task_service,
            page=callback_data.page,
        )
        if kb is None:
            await cb.message.edit_text(text)
        else:
            await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


# ---------- Users ----------


@router.message(F.text == BTN_USERS)
@router.message(Command("users"))
async def list_users(
    message: Message, state: FSMContext, user_service: UserService
) -> None:
    await state.clear()
    users = await user_service.list_all()
    if not users:
        await message.answer("Пользователей нет.")
        return

    by_role: dict[Role, list[User]] = {}
    for u in users:
        by_role.setdefault(u.role, []).append(u)

    lines: list[str] = [
        "<b>Пользователи:</b>",
        "",
        "<i>Нажмите на пользователя, чтобы открыть карточку "
        "(переименовать / заблокировать / удалить).</i>",
        "",
    ]
    for role in (Role.ADMIN, Role.DESIGNER, Role.CUSTOMER):
        chunk = by_role.get(role, [])
        if not chunk:
            continue
        lines.append(f"<b>{role.label}</b> ({len(chunk)}):")
        for u in chunk:
            flag = "" if u.is_active else " 🚫"
            lines.append(f" · #{u.id} {escape(u.full_name)}{flag}")
        lines.append("")

    await message.answer(
        "\n".join(lines), reply_markup=users_admin_keyboard(users)
    )


# ---------- User card ----------


async def _render_user_card(
    cb: CallbackQuery,
    *,
    target: User,
    user_service: UserService,
) -> None:
    """Render a single-user management card with all admin actions."""
    deps = await user_service.dependencies(target.id)
    status_label = "Активен" if target.is_active else "🚫 Заблокирован"

    lines = [
        f"<b>👤 #{target.id} {escape(target.full_name)}</b>",
        "",
        f"<b>Роль:</b> {target.role.label}",
        f"<b>Статус:</b> {status_label}",
        f"<b>Telegram ID:</b> <code>{target.telegram_id}</code>",
        "",
        "<b>Связи:</b>",
        f" · Задач как заказчик: <b>{deps.tasks_as_customer}</b>",
        f" · Задач как дизайнер: <b>{deps.tasks_as_designer}</b>",
        f" · Комментариев: <b>{deps.comments}</b>",
        f" · Файлов: <b>{deps.attachments}</b>",
    ]

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "\n".join(lines), reply_markup=user_card_admin_keyboard(target)
        )


@router.callback_query(UserAdminCallback.filter(F.action == "open"))
async def user_card_open(
    cb: CallbackQuery,
    callback_data: UserAdminCallback,
    user_service: UserService,
) -> None:
    target = await user_service.get_by_id(callback_data.user_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    await _render_user_card(cb, target=target, user_service=user_service)
    await cb.answer()


@router.callback_query(UserAdminCallback.filter(F.action == "back"))
async def user_card_back(
    cb: CallbackQuery, user_service: UserService
) -> None:
    """Return from a user card back to the users list."""
    users = await user_service.list_all()
    if not users:
        if isinstance(cb.message, Message):
            await cb.message.edit_text("Пользователей нет.")
        await cb.answer()
        return

    by_role: dict[Role, list[User]] = {}
    for u in users:
        by_role.setdefault(u.role, []).append(u)

    lines: list[str] = [
        "<b>Пользователи:</b>",
        "",
        "<i>Нажмите на пользователя, чтобы открыть карточку.</i>",
        "",
    ]
    for role in (Role.ADMIN, Role.DESIGNER, Role.CUSTOMER):
        chunk = by_role.get(role, [])
        if not chunk:
            continue
        lines.append(f"<b>{role.label}</b> ({len(chunk)}):")
        for u in chunk:
            flag = "" if u.is_active else " 🚫"
            lines.append(f" · #{u.id} {escape(u.full_name)}{flag}")
        lines.append("")

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "\n".join(lines), reply_markup=users_admin_keyboard(users)
        )
    await cb.answer()


# ---------- Rename user ----------


@router.callback_query(UserAdminCallback.filter(F.action == "rename"))
async def rename_user_start(
    cb: CallbackQuery,
    callback_data: UserAdminCallback,
    state: FSMContext,
    user_service: UserService,
) -> None:
    target = await user_service.get_by_id(callback_data.user_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    await state.set_state(AdminRenameUser.waiting_name)
    await state.update_data(user_id=target.id)
    if isinstance(cb.message, Message):
        await cb.message.answer(
            f"Введите новое имя для <b>{escape(target.full_name)}</b> "
            f"(#{target.id}, {target.role.label}).\n\n"
            "Чтобы отменить — /cancel."
        )
    await cb.answer()


@router.message(AdminRenameUser.waiting_name, F.text)
async def rename_user_apply(
    message: Message,
    state: FSMContext,
    user_service: UserService,
) -> None:
    data = await state.get_data()
    user_id = int(data.get("user_id", 0))
    if not user_id:
        await state.clear()
        return
    try:
        updated = await user_service.rename(
            user_id=user_id, full_name=message.text or ""
        )
    except UserServiceError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✏️ Имя пользователя #{updated.id} изменено на "
        f"<b>{escape(updated.full_name)}</b>."
    )


# ---------- Block / unblock via user card ----------


@router.callback_query(UserAdminCallback.filter(F.action == "block"))
async def user_block_ask(
    cb: CallbackQuery,
    callback_data: UserAdminCallback,
    user_service: UserService,
) -> None:
    target = await user_service.get_by_id(callback_data.user_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"<b>🚫 Заблокировать пользователя?</b>\n\n"
            f"#{target.id} {escape(target.full_name)} ({target.role.label})\n\n"
            "<i>Данные пользователя останутся в системе, но он не сможет "
            "взаимодействовать с ботом до разблокировки.</i>",
            reply_markup=confirm_keyboard(
                action="block_user", target_id=target.id
            ),
        )
    await cb.answer()


@router.callback_query(ConfirmCallback.filter(F.action == "block_user"))
async def user_block_confirm(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    user: User,
    user_service: UserService,
) -> None:
    target = await user_service.get_by_id(callback_data.target_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    if not callback_data.yes:
        await _render_user_card(cb, target=target, user_service=user_service)
        await cb.answer("Отменено")
        return
    try:
        await user_service.block(target=target, actor=user)
    except UserServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    refreshed = await user_service.get_by_id(target.id)
    if refreshed is not None:
        await _render_user_card(
            cb, target=refreshed, user_service=user_service
        )
    await cb.answer("Заблокировано")


@router.callback_query(UserAdminCallback.filter(F.action == "unblock"))
async def user_unblock(
    cb: CallbackQuery,
    callback_data: UserAdminCallback,
    user: User,
    user_service: UserService,
) -> None:
    target = await user_service.get_by_id(callback_data.user_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    try:
        await user_service.unblock(target=target, actor=user)
    except UserServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    refreshed = await user_service.get_by_id(target.id)
    if refreshed is not None:
        await _render_user_card(
            cb, target=refreshed, user_service=user_service
        )
    await cb.answer("Разблокировано")


# ---------- Delete user ----------


@router.callback_query(UserAdminCallback.filter(F.action == "delete"))
async def user_delete_ask(
    cb: CallbackQuery,
    callback_data: UserAdminCallback,
    user_service: UserService,
    task_service: TaskService,
) -> None:
    target = await user_service.get_by_id(callback_data.user_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return

    deps = await user_service.dependencies(target.id)
    active_designer_tasks = 0
    if target.role == Role.DESIGNER:
        active_designer_tasks = await task_service.count_active_for_designer(
            target.id
        )

    cascade_lines: list[str] = []
    if deps.tasks_as_customer:
        cascade_lines.append(
            f" · удалятся задачи заказчика: <b>{deps.tasks_as_customer}</b> "
            "(вместе с их комментариями и файлами)"
        )
    if target.role == Role.DESIGNER and active_designer_tasks:
        cascade_lines.append(
            f" · активных задач дизайнера: <b>{active_designer_tasks}</b> "
            "— выберите ниже, что с ними делать"
        )
    elif deps.tasks_as_designer:
        cascade_lines.append(
            f" · задачи, где он был дизайнером: <b>{deps.tasks_as_designer}</b> "
            "(останутся без исполнителя)"
        )
    if deps.comments:
        cascade_lines.append(
            f" · {deps.comments} комментариев в чужих задачах "
            "сохранятся без автора"
        )
    if deps.attachments:
        cascade_lines.append(
            f" · {deps.attachments} файлов в чужих задачах "
            "сохранятся без автора"
        )

    text = [
        "<b>🗑 Удалить пользователя?</b>",
        "",
        f"#{target.id} {escape(target.full_name)} ({target.role.label})",
    ]
    if cascade_lines:
        text.append("")
        text.append("<b>Последствия:</b>")
        text.extend(cascade_lines)
    text.append("")
    text.append(
        "<i>Это действие необратимо. Если нужно лишь временно "
        "запретить доступ — воспользуйтесь блокировкой.</i>"
    )

    # Designers with active workload get a three-way picker
    # (redistribute / just-drop / cancel).  Everyone else gets the
    # standard yes/no confirm, since there's nothing to redistribute.
    if target.role == Role.DESIGNER and active_designer_tasks:
        markup = user_delete_choice_keyboard(target.id)
    else:
        markup = confirm_keyboard(
            action="del_user_drop", target_id=target.id
        )

    if isinstance(cb.message, Message):
        await cb.message.edit_text("\n".join(text), reply_markup=markup)
    await cb.answer()


async def _execute_user_delete(
    cb: CallbackQuery,
    *,
    target: User,
    actor: User,
    redistribute: bool,
    user_service: UserService,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    """Shared body for the two designer-deletion flows.

    Parameters
    ----------
    redistribute:
        ``True`` — migrate the designer's active tasks to the rest of
        the team before deleting the user.
        ``False`` — drop the user immediately; active tasks lose
        ``designer_id`` via FK ``ON DELETE SET NULL`` and the customers
        get an "orphaned task" notification.
    """
    target_name = target.full_name
    target_id = target.id
    target_was_designer = target.role == Role.DESIGNER

    # Capture orphaned tasks *before* the user row vanishes, so we can
    # send proper notifications about the un-assignment that's about
    # to happen.
    orphaned_tasks: list[Task] = []
    redistributed: list[tuple[Task, User | None]] = []

    if target_was_designer:
        if redistribute:
            other_designers = [
                d
                for d in await user_service.list_designers()
                if d.id != target.id and d.is_active
            ]
            redistributed = await task_service.redistribute_designer_tasks(
                departing=target, candidates=other_designers
            )
        else:
            orphaned_tasks = await task_service.list_active_for_designer(
                target.id
            )

    try:
        deps = await user_service.delete(target=target, actor=actor)
    except UserServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    reason = f"Дизайнер {target_name} удалён администратором."
    reassigned_count = 0
    orphaned_count = 0

    for task, new_designer in redistributed:
        refreshed = await task_service.get_task(task.id)
        if refreshed is None:
            continue
        if new_designer is not None:
            await notifications.notify_task_reassigned_auto(
                task=refreshed, new_designer=new_designer, reason=reason
            )
            reassigned_count += 1
        else:
            recipients: list[User] = []
            if refreshed.customer is not None:
                recipients.append(refreshed.customer)
            await notifications.notify_task_unassigned_auto(
                task=refreshed, recipients=recipients, reason=reason
            )
            orphaned_count += 1

    # "Just delete" path — designer's tasks were un-linked by the DB,
    # but the customers should still know their work has no assignee.
    for task in orphaned_tasks:
        refreshed = await task_service.get_task(task.id)
        if refreshed is None:
            continue
        recipients = []
        if refreshed.customer is not None:
            recipients.append(refreshed.customer)
        await notifications.notify_task_unassigned_auto(
            task=refreshed, recipients=recipients, reason=reason
        )
        orphaned_count += 1

    extras: list[str] = []
    if deps.tasks_as_customer:
        extras.append(f"удалено задач: {deps.tasks_as_customer}")
    if reassigned_count:
        extras.append(f"переназначено задач: {reassigned_count}")
    if orphaned_count:
        extras.append(f"без исполнителя осталось: {orphaned_count}")
    extras_text = (
        f"\n<i>{'; '.join(extras).capitalize()}.</i>" if extras else ""
    )

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"🗑 Пользователь <b>{escape(target_name)}</b> "
            f"(#{target_id}) удалён.{extras_text}"
        )
    await cb.answer("Удалено")


@router.callback_query(ConfirmCallback.filter(F.action == "del_user_drop"))
async def user_delete_drop(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    user: User,
    user_service: UserService,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    """Delete user without redistributing their tasks."""
    target = await user_service.get_by_id(callback_data.target_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    if not callback_data.yes:
        await _render_user_card(cb, target=target, user_service=user_service)
        await cb.answer("Отменено")
        return
    await _execute_user_delete(
        cb,
        target=target,
        actor=user,
        redistribute=False,
        user_service=user_service,
        task_service=task_service,
        notifications=notifications,
    )


@router.callback_query(ConfirmCallback.filter(F.action == "del_user_dist"))
async def user_delete_dist(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    user: User,
    user_service: UserService,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    """Delete user and redistribute their active tasks to the team."""
    target = await user_service.get_by_id(callback_data.target_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    if not callback_data.yes:
        await _render_user_card(cb, target=target, user_service=user_service)
        await cb.answer("Отменено")
        return
    await _execute_user_delete(
        cb,
        target=target,
        actor=user,
        redistribute=True,
        user_service=user_service,
        task_service=task_service,
        notifications=notifications,
    )


# ---------- Stats ----------


_ACTIVE_STATUSES: tuple[TaskStatus, ...] = (
    TaskStatus.NEW,
    TaskStatus.IN_PROGRESS,
    TaskStatus.WAITING_REVIEW,
    TaskStatus.NEEDS_REVISION,
)
_FINISHED_STATUSES: tuple[TaskStatus, ...] = (TaskStatus.DONE,)


def _format_user_breakdown(
    title: str,
    rows: list[tuple[User, dict[TaskStatus, int]]],
) -> list[str]:
    """Render a per-user task breakdown with totals."""
    out: list[str] = [f"<b>{title}</b>"]
    if not rows:
        out.append("  <i>нет данных</i>")
        return out

    # Sort by total desc to surface the most loaded user first
    rows_sorted = sorted(
        rows, key=lambda item: sum(item[1].values()), reverse=True
    )

    for user, counts in rows_sorted:
        total = sum(counts.values())
        active = sum(counts.get(s, 0) for s in _ACTIVE_STATUSES)
        finished = sum(counts.get(s, 0) for s in _FINISHED_STATUSES)

        out.append(
            f"\n· <b>{escape(user.full_name)}</b> · #{user.id} "
            f"(всего: {total}, активных: {active}, завершённых: {finished})"
        )
        # Per-status row, skipping zero counts
        bits: list[str] = []
        for status in TaskStatus:
            n = counts.get(status, 0)
            if n:
                bits.append(f"{status.label}: <b>{n}</b>")
        if bits:
            out.append("   " + " · ".join(bits))
    return out


@router.message(F.text == BTN_STATS)
@router.message(Command("stats"))
async def stats(
    message: Message,
    task_service: TaskService,
    user_service: UserService,
) -> None:
    role_counts = await user_service.role_counts()
    task_counts = await task_service.stats()
    by_designer = await task_service.stats_by_designer()
    by_customer = await task_service.stats_by_customer()
    overdue = await task_service.overdue_count()

    total_tasks = sum(task_counts.values())
    active_total = sum(task_counts.get(s, 0) for s in _ACTIVE_STATUSES)
    finished_total = sum(task_counts.get(s, 0) for s in _FINISHED_STATUSES)

    lines: list[str] = ["📊 <b>Статистика</b>", ""]

    # --- Users
    lines.append("👥 <b>Пользователи</b>")
    for role in Role:
        lines.append(f"  · {role.label}: <b>{role_counts.get(role, 0)}</b>")

    # --- Tasks overall
    lines.append("")
    lines.append("📋 <b>Задачи — всего</b>")
    lines.append(
        f"  · Всего: <b>{total_tasks}</b> "
        f"(активных: <b>{active_total}</b>, "
        f"завершённых: <b>{finished_total}</b>)"
    )
    if overdue:
        lines.append(f"  · ⚠️ Просроченных: <b>{overdue}</b>")
    for status in TaskStatus:
        n = task_counts.get(status, 0)
        if n:
            lines.append(f"  · {status.label}: <b>{n}</b>")

    # --- By designer
    lines.append("")
    lines.extend(_format_user_breakdown("🛠 Дизайнеры", by_designer))

    # --- By customer
    lines.append("")
    lines.extend(_format_user_breakdown("📝 Заказчики", by_customer))

    text = "\n".join(lines)
    # Telegram message hard limit is 4096 chars; split if needed.
    if len(text) <= 4000:
        await message.answer(text)
        return

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > 3800 and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    for chunk in chunks:
        await message.answer(chunk)


# ---------- Role assignment ----------


@router.message(F.text == BTN_ASSIGN_ROLE)
@router.message(Command("addrole"))
async def addrole_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminAssignRole.telegram_id)
    await message.answer(
        "Отправьте числовой Telegram ID пользователя, которому нужно установить роль."
    )


@router.message(AdminAssignRole.telegram_id, F.text)
async def addrole_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Ожидаю числовой ID.")
        return
    await state.update_data(telegram_id=int(text))
    await state.set_state(AdminAssignRole.full_name)
    await message.answer("Введите имя пользователя для отображения.")


@router.message(AdminAssignRole.full_name, F.text)
async def addrole_name(message: Message, state: FSMContext) -> None:
    try:
        name = UserService.validate_full_name(message.text or "")
    except UserServiceError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(full_name=name)
    await state.set_state(AdminAssignRole.role)
    await message.answer(
        "Выберите роль:", reply_markup=admin_assign_role_keyboard()
    )


@router.callback_query(AdminAssignRole.role, RolePickerCallback.filter())
async def addrole_choose(
    cb: CallbackQuery,
    callback_data: RolePickerCallback,
    state: FSMContext,
    user_service: UserService,
    user: User,
) -> None:
    data = await state.get_data()
    try:
        role = Role(callback_data.role)
    except ValueError:
        await cb.answer("Неизвестная роль", show_alert=True)
        return

    target = await user_service.assign_role(
        telegram_id=int(data["telegram_id"]),
        role=role,
        full_name=data["full_name"],
    )

    await state.clear()
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Пользователю <b>{escape(target.full_name)}</b> "
            f"(tg <code>{target.telegram_id}</code>) назначена роль "
            f"<b>{role.label}</b>."
        )
    await cb.answer("Готово")


# ---------- Toggle user active ----------


@router.message(Command("ban"))
async def cmd_ban(message: Message, user_service: UserService) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/ban &lt;user_id&gt;</code>")
        return
    target = await user_service.get_by_id(int(parts[1]))
    if target is None:
        await message.answer("Пользователь не найден.")
        return
    if target.role == Role.ADMIN:
        await message.answer("Нельзя заблокировать другого администратора.")
        return
    await message.answer(
        f"Подтвердите блокировку пользователя "
        f"<b>{escape(target.full_name)}</b> (#{target.id}, {target.role.label})?",
        reply_markup=confirm_keyboard(action="ban_user", target_id=target.id),
    )


@router.message(Command("unban"))
async def cmd_unban(
    message: Message, user: User, user_service: UserService
) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/unban &lt;user_id&gt;</code>")
        return
    target = await user_service.get_by_id(int(parts[1]))
    if target is None:
        await message.answer("Пользователь не найден.")
        return
    try:
        await user_service.unblock(target=target, actor=user)
    except UserServiceError as exc:
        await message.answer(str(exc))
        return
    await message.answer(f"Пользователь #{target.id} разблокирован.")


# ---------- Confirmation handlers ----------


@router.callback_query(ConfirmCallback.filter(F.action == "ban_user"))
async def confirm_ban(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    user: User,
    user_service: UserService,
) -> None:
    if not callback_data.yes:
        if isinstance(cb.message, Message):
            await cb.message.edit_text("Блокировка отменена.")
        await cb.answer()
        return
    target = await user_service.get_by_id(callback_data.target_id)
    if target is None:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    try:
        await user_service.block(target=target, actor=user)
    except UserServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"🚫 Пользователь <b>{escape(target.full_name)}</b> (#{target.id}) "
            "заблокирован."
        )
    await cb.answer("Готово")


# ---------- Invites: menu ----------


@router.message(F.text == BTN_INVITES)
@router.message(Command("invites"))
async def invites_open(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "<b>🎟 Инвайт-коды</b>\n\n"
        "Инвайт — одноразовый код, который позволяет новому пользователю "
        "войти в бот с заранее определённой ролью.",
        reply_markup=invites_menu_keyboard(),
    )


@router.callback_query(InviteMenuCallback.filter(F.action == "close"))
async def invites_close(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "<b>🎟 Инвайт-коды</b>\n\n"
            "Выберите действие:",
            reply_markup=invites_menu_keyboard(),
        )
    await cb.answer()


@router.callback_query(InviteMenuCallback.filter(F.action == "create"))
async def invites_create_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateInviteStates.role)
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "Выберите роль, на которую выдаётся инвайт:",
            reply_markup=invite_role_picker(),
        )
    await cb.answer()


@router.callback_query(CreateInviteStates.role, InviteRoleCallback.filter())
async def invites_create_role(
    cb: CallbackQuery,
    callback_data: InviteRoleCallback,
    state: FSMContext,
) -> None:
    try:
        role = Role(callback_data.role)
    except ValueError:
        await cb.answer("Неизвестная роль", show_alert=True)
        return
    if role == Role.ADMIN:
        await cb.answer("Инвайт на ADMIN запрещён", show_alert=True)
        return
    await state.update_data(invite_role=role.value)
    await state.set_state(CreateInviteStates.ttl)
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Роль: <b>{role.label}</b>.\n\nВыберите срок действия:",
            reply_markup=invite_ttl_picker(),
        )
    await cb.answer()


@router.callback_query(CreateInviteStates.ttl, InviteTtlCallback.filter())
async def invites_create_ttl(
    cb: CallbackQuery,
    callback_data: InviteTtlCallback,
    state: FSMContext,
) -> None:
    """Ask how many invites to create for the chosen role/TTL."""
    data = await state.get_data()
    try:
        role = Role(str(data.get("invite_role")))
        parse_ttl(callback_data.ttl)  # validate token now, parse again later
    except (InviteServiceError, ValueError) as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    await state.update_data(invite_ttl=callback_data.ttl)
    await state.set_state(CreateInviteStates.count)

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Роль: <b>{role.label}</b>.\n\n"
            "Сколько кодов сгенерировать за один раз?",
            reply_markup=invite_count_picker(),
        )
    await cb.answer()


@router.callback_query(CreateInviteStates.count, InviteCountCallback.filter())
async def invites_create_count(
    cb: CallbackQuery,
    callback_data: InviteCountCallback,
    state: FSMContext,
    user: User,
    invite_service: InviteService,
    bot: Bot,
) -> None:
    data = await state.get_data()
    try:
        role = Role(str(data.get("invite_role")))
        ttl = parse_ttl(str(data.get("invite_ttl", "inf")))
    except (InviteServiceError, ValueError) as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    count = max(1, int(callback_data.count))

    try:
        invites = await invite_service.create_invites_bulk(
            creator=user, role=role, ttl=ttl, count=count
        )
    except InviteServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    await state.clear()

    bot_user = await bot.me()
    expires = (
        f"действует до {format_dt(invites[0].expires_at)}"
        if invites[0].expires_at
        else "без ограничения по времени"
    )

    lines: list[str] = [
        f"<b>✅ Создано инвайтов: {len(invites)}</b>",
        "",
        f"<b>Роль:</b> {role.label}",
        f"<b>Срок:</b> {expires}",
        "",
    ]
    for inv in invites:
        if bot_user.username:
            link = f"https://t.me/{bot_user.username}?start={inv.code}"
            lines.append(
                f"#{inv.id} · <code>{inv.code}</code>\n{link}"
            )
        else:
            lines.append(f"#{inv.id} · <code>{inv.code}</code>")
        lines.append("")

    lines.append(
        "<i>Передайте коды / ссылки пользователям. "
        "Каждый код одноразовый.</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="« К меню инвайтов",
        callback_data=InviteMenuCallback(action="close").pack(),
    )
    builder.adjust(1)

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "\n".join(lines), reply_markup=builder.as_markup()
        )
    await cb.answer(f"Создано {len(invites)} инвайтов")


@router.callback_query(InviteMenuCallback.filter(F.action == "list"))
async def invites_list(
    cb: CallbackQuery, invite_service: InviteService
) -> None:
    invites = await invite_service.list_active()
    if not invites:
        if isinstance(cb.message, Message):
            await cb.message.edit_text(
                "Активных инвайтов нет.",
                reply_markup=invites_menu_keyboard(),
            )
        await cb.answer()
        return

    lines: list[str] = ["<b>Активные инвайты</b>", ""]
    builder = InlineKeyboardBuilder()
    for inv in invites:
        expires = (
            f"до {format_dt(inv.expires_at)}"
            if inv.expires_at
            else "без ограничений"
        )
        lines.append(
            f"#{inv.id} · <b>{inv.role.label}</b> · {expires}\n"
            f"<code>{inv.code}</code>"
        )
        lines.append("")
        builder.button(
            text=f"🗑 Отозвать #{inv.id}",
            callback_data=ConfirmCallback(
                action="revoke_invite_ask",
                target_id=inv.id,
                yes=False,
            ).pack(),
        )
    builder.button(
        text="« Закрыть",
        callback_data=InviteMenuCallback(action="close").pack(),
    )
    builder.adjust(1)

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "\n".join(lines), reply_markup=builder.as_markup()
        )
    await cb.answer()


@router.callback_query(ConfirmCallback.filter(F.action == "revoke_invite_ask"))
async def invites_revoke_ask(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    invite_service: InviteService,
) -> None:
    invite = await invite_service.get(callback_data.target_id)
    if invite is None:
        await cb.answer("Инвайт не найден", show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Подтвердите отзыв инвайта #{invite.id} "
            f"(роль <b>{invite.role.label}</b>, "
            f"код <code>{invite.code}</code>)?",
            reply_markup=confirm_keyboard(
                action="revoke_invite", target_id=invite.id
            ),
        )
    await cb.answer()


@router.callback_query(ConfirmCallback.filter(F.action == "revoke_invite"))
async def invites_revoke(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    user: User,
    invite_service: InviteService,
) -> None:
    if not callback_data.yes:
        if isinstance(cb.message, Message):
            await cb.message.edit_text(
                "Готово. Инвайт остаётся активным.",
                reply_markup=invites_menu_keyboard(),
            )
        await cb.answer()
        return
    try:
        invite = await invite_service.revoke(
            invite_id=callback_data.target_id, actor=user
        )
    except InviteServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"🗑 Инвайт #{invite.id} (роль {invite.role.label}) отозван.",
            reply_markup=invites_menu_keyboard(),
        )
    await cb.answer("Отозвано")


# ---------- Reassign designer ----------


@router.callback_query(AdminTaskCallback.filter(F.action == "reassign"))
async def admin_reassign_start(
    cb: CallbackQuery,
    callback_data: AdminTaskCallback,
    user_service: UserService,
) -> None:
    designers = await user_service.list_designers()
    if not designers:
        await cb.answer("Нет доступных дизайнеров.", show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Выберите нового дизайнера для задачи #{callback_data.task_id}:",
            reply_markup=designer_picker_keyboard(
                designers, scope="reassign", task_id=callback_data.task_id
            ),
        )
    await cb.answer()


@router.callback_query(DesignerPickerCallback.filter(F.scope == "reassign"))
async def admin_reassign_finish(
    cb: CallbackQuery,
    callback_data: DesignerPickerCallback,
    user: User,
    task_service: TaskService,
    user_service: UserService,
    notifications: NotificationService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return
    new_designer = await user_service.get_by_id(callback_data.designer_id)
    if new_designer is None or new_designer.role != Role.DESIGNER:
        await cb.answer("Дизайнер не найден", show_alert=True)
        return

    previous_designer_id = task.designer_id
    try:
        await task_service.reassign_designer(
            task, designer=new_designer, actor=user
        )
    except TaskServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    refreshed = await task_service.get_task(task.id)
    if refreshed is not None and refreshed.designer:
        await notifications.notify_task_assigned(task=refreshed, designer=refreshed.designer)

    if previous_designer_id and previous_designer_id != new_designer.id:
        previous_designer = await user_service.get_by_id(previous_designer_id)
        if previous_designer is not None:
            await notifications.notify_task_unassigned(
                designer=previous_designer, task=task
            )

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Задача <b>#{task.id}</b> переназначена на "
            f"<b>{escape(new_designer.full_name)}</b>."
        )
    await cb.answer("Готово")


# ---------- Rendering helpers ----------


async def _send(
    message: Message,
    *,
    scope: str,
    flt: TaskFilter,
    task_service: TaskService,
    user: User,
    page: int = 0,
) -> None:
    text, kb = await _render(
        scope=scope, flt=flt, task_service=task_service, page=page
    )
    if kb is None:
        await message.answer(text, reply_markup=main_menu(user.role))
    else:
        await message.answer(text, reply_markup=kb)


async def _render(
    *,
    scope: str,
    flt: TaskFilter,
    task_service: TaskService,
    page: int,
) -> tuple[str, Any]:
    tasks, total = await task_service.list_paginated(
        flt, page=page, page_size=DEFAULT_PAGE_SIZE
    )
    if not tasks:
        return "Задачи не найдены.", None

    meta = paginate_meta(page=page, page_size=DEFAULT_PAGE_SIZE, total=total)

    builder = InlineKeyboardBuilder()
    lines: list[str] = [f"<b>Найдено: {total}</b>", ""]
    for t in tasks:
        lines.append(format_task_short(t, viewer_role=Role.ADMIN))
        lines.append("")
        builder.button(
            text=f"Открыть #{t.id}",
            callback_data=TaskActionCallback(action="open", task_id=t.id).pack(),
        )
    builder.adjust(1)

    nav = pagination_keyboard(
        scope=scope, page=meta.page, has_prev=meta.has_prev, has_next=meta.has_next
    )
    for row in nav.inline_keyboard:
        builder.row(
            *[
                InlineKeyboardButton(text=b.text, callback_data=b.callback_data)
                for b in row
            ]
        )

    return "\n".join(lines), builder.as_markup()
