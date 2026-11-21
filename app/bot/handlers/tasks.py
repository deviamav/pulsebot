"""Shared task handlers: card view, status changes, attachment uploads."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from datetime import datetime, time, timedelta, timezone

from app.bot.filters import RoleFilter
from app.bot.keyboards import (
    ConfirmCallback,
    StatusChangeCallback,
    TaskActionCallback,
    TaskDeadlineCallback,
    TaskEditCallback,
    TaskPriorityCallback,
    confirm_keyboard,
    task_card_keyboard,
    task_deadline_picker,
    task_edit_menu_keyboard,
    task_priority_picker,
)
from app.bot.keyboards.reply import ALL_MENU_BUTTONS
from app.bot.states import AttachFileStates, EditTaskStates, TaskFocus
from app.bot.utils.formatting import (
    format_comments_timeline,
    format_task_card_for_role,
)
from app.db.models import Priority, Role, TaskStatus, User
from app.services import (
    AttachmentService,
    CommentService,
    NotificationService,
    TaskService,
)
from app.services.attachment import AttachmentServiceError
from app.services.comment import CommentServiceError
from app.services.task import TaskServiceError
from app.utils.datetime import format_dt, parse_deadline

router = Router(name="tasks")
router.message.filter(RoleFilter(Role.ADMIN, Role.CUSTOMER, Role.DESIGNER))
router.callback_query.filter(RoleFilter(Role.ADMIN, Role.CUSTOMER, Role.DESIGNER))


def _gather_recipients(*, task: Any, actor: User) -> list[User]:
    """Return participating stakeholders (customer + designer) except the actor.

    Admins are intentionally excluded: they observe progress through
    the statistics screen / "All tasks" listing rather than receiving
    every status update and comment as a live notification.
    """
    recipients: list[User] = []
    if task.customer is not None and task.customer.id != actor.id:
        recipients.append(task.customer)
    if task.designer is not None and task.designer.id != actor.id:
        recipients.append(task.designer)
    return recipients


# ---------- Open task card ----------


@router.callback_query(TaskActionCallback.filter(F.action == "open"))
async def open_task(
    cb: CallbackQuery,
    callback_data: TaskActionCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return
    if not task_service.can_view(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return

    comments = await comment_service.list_for_task(task.id)
    attachments = await attachment_service.list_for_task(task.id)

    card = format_task_card_for_role(task, viewer_role=user.role)
    text_lines = [card]
    if attachments:
        text_lines.append("")
        text_lines.append(
            f"<b>📎 Файлов:</b> {len(attachments)} (приходят ниже)"
        )
    if comments:
        text_lines.append("")
        text_lines.append("<b>💬 Комментарии:</b>")
        text_lines.append(format_comments_timeline(comments))

    # Quick-input hint: text/files sent right now go straight to this task.
    text_lines.append("")
    text_lines.append(
        "💡 <i>Просто пришлите сообщение или файл — добавится "
        "к этой задаче.</i>"
    )

    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "\n".join(text_lines),
            reply_markup=task_card_keyboard(
                task_id=task.id,
                viewer_role=user.role,
                status=task.status,
                is_assigned=task.designer_id == user.id,
            ),
        )

        # Relay attachments anonymously. Same-type files come as one
        # media album (Telegram limit is 10 per group).
        if attachments:
            await notifications.send_attachments(
                chat_id=cb.message.chat.id, attachments=attachments
            )

    # Activate "this task is in focus" mode: any subsequent plain
    # message / file will be routed straight to this task.
    await state.set_state(TaskFocus.active)
    await state.update_data(active_task_id=task.id)
    await cb.answer()


@router.callback_query(TaskActionCallback.filter(F.action == "back"))
async def back_from_task(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "Выберите пункт меню ниже, чтобы посмотреть задачи."
        )
    await cb.answer()


# ---------- Status changes ----------


# Statuses that require a confirmation prompt (one-step "Are you sure?")
# before the transition is actually applied.
_DESTRUCTIVE_STATUSES = {TaskStatus.DONE}


# Status transitions where the *opposite* side must act and therefore
# deserves a proactive full-card notification (with attachments and an
# inline action keyboard) instead of a short status update.
_STATUS_HEADERS: dict[TaskStatus, str] = {
    TaskStatus.WAITING_REVIEW: "🔎 Задача отправлена на проверку",
    TaskStatus.NEEDS_REVISION: "✏️ Задача возвращена на доработку",
    TaskStatus.DONE: "🎉 Задача принята как выполненная",
}


def _proactive_card_recipient(task: Any, new_status: TaskStatus) -> User | None:
    """Pick the participant who must immediately see the full task card."""
    if new_status == TaskStatus.WAITING_REVIEW:
        return task.customer
    if new_status == TaskStatus.NEEDS_REVISION:
        return task.designer
    if new_status == TaskStatus.DONE:
        return task.designer
    return None


@router.callback_query(StatusChangeCallback.filter())
async def change_status(
    cb: CallbackQuery,
    callback_data: StatusChangeCallback,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return

    try:
        new_status = TaskStatus(callback_data.status)
    except ValueError:
        await cb.answer("Неизвестный статус", show_alert=True)
        return

    if new_status in _DESTRUCTIVE_STATUSES:
        if isinstance(cb.message, Message):
            await cb.message.edit_text(
                f"<b>Подтвердите действие</b>\n\n"
                f"Принять задачу <b>#{task.id} — {task.title}</b> "
                "как выполненную?",
                reply_markup=confirm_keyboard(
                    action="done_task", target_id=task.id
                ),
            )
        await cb.answer()
        return

    await _apply_status_change(
        cb=cb,
        task_id=task.id,
        new_status=new_status,
        user=user,
        task_service=task_service,
        notifications=notifications,
        comment_service=comment_service,
        attachment_service=attachment_service,
    )


async def _apply_status_change(
    *,
    cb: CallbackQuery,
    task_id: int,
    new_status: TaskStatus,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
) -> None:
    task = await task_service.get_task(task_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return

    try:
        updated = await task_service.change_status(
            task, new_status=new_status, actor=user
        )
    except TaskServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    refreshed = await task_service.get_task(updated.id)
    if refreshed is not None:
        recipients = _gather_recipients(task=refreshed, actor=user)

        # Decide whether the new status warrants a proactive full-card
        # notification for the actionable participant.
        full_card_target = _proactive_card_recipient(refreshed, new_status)
        if (
            full_card_target is not None
            and full_card_target.id != user.id
        ):
            attachments = await attachment_service.list_for_task(refreshed.id)
            comments = await comment_service.list_for_task(refreshed.id)
            kb = task_card_keyboard(
                task_id=refreshed.id,
                viewer_role=full_card_target.role,
                status=refreshed.status,
                is_assigned=refreshed.designer_id == full_card_target.id,
            )
            await notifications.notify_task_card(
                task=refreshed,
                recipient=full_card_target,
                attachments=attachments,
                comments=comments,
                header=_STATUS_HEADERS.get(new_status),
                keyboard=kb,
            )
            # Don't double-notify: drop them from the short-update list.
            recipients = [
                r for r in recipients if r.id != full_card_target.id
            ]

        if recipients:
            await notifications.notify_status_change(
                task=refreshed, actor_role=user.role, recipients=recipients
            )

        if isinstance(cb.message, Message):
            await cb.message.edit_text(
                format_task_card_for_role(refreshed, viewer_role=user.role),
                reply_markup=task_card_keyboard(
                    task_id=refreshed.id,
                    viewer_role=user.role,
                    status=refreshed.status,
                    is_assigned=refreshed.designer_id == user.id,
                ),
            )
    await cb.answer("Статус обновлён")


@router.callback_query(
    ConfirmCallback.filter(F.action == "done_task")
)
async def confirm_status_change(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
) -> None:
    if not callback_data.yes:
        task = await task_service.get_task(callback_data.target_id)
        if task is not None and isinstance(cb.message, Message):
            await cb.message.edit_text(
                format_task_card_for_role(task, viewer_role=user.role),
                reply_markup=task_card_keyboard(
                    task_id=task.id,
                    viewer_role=user.role,
                    status=task.status,
                    is_assigned=task.designer_id == user.id,
                ),
            )
        await cb.answer("Отменено")
        return

    await _apply_status_change(
        cb=cb,
        task_id=callback_data.target_id,
        new_status=TaskStatus.DONE,
        user=user,
        task_service=task_service,
        notifications=notifications,
        comment_service=comment_service,
        attachment_service=attachment_service,
    )


# ---------- Attach file to existing task ----------


@router.callback_query(TaskActionCallback.filter(F.action == "attach"))
async def attach_start(
    cb: CallbackQuery,
    callback_data: TaskActionCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    attachment_service: AttachmentService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not attachment_service.can_attach(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AttachFileStates.waiting_files)
    await state.update_data(task_id=task.id)
    if isinstance(cb.message, Message):
        await cb.message.answer(
            f"Отправьте файл (фото/документ) для задачи #{task.id}.\n"
            "Чтобы отменить: /cancel"
        )
    await cb.answer()


def _media_payload(m: Message) -> dict[str, Any] | None:
    """Pull the payload (file_id + metadata) out of a Telegram message
    containing either a document or a photo."""
    if m.document:
        return {
            "telegram_file_id": m.document.file_id,
            "file_unique_id": m.document.file_unique_id,
            "file_name": m.document.file_name,
            "mime_type": m.document.mime_type,
            "media_type": "document",
        }
    if m.photo:
        photo = m.photo[-1]
        return {
            "telegram_file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_name": None,
            "mime_type": "image/jpeg",
            "media_type": "photo",
        }
    return None


async def _save_attachments_batch(
    *,
    task: Any,
    user: User,
    messages: list[Message],
    attachment_service: AttachmentService,
) -> list[Any]:
    """Persist every photo/document in ``messages`` and return the
    created :class:`Attachment` rows (errors are silently skipped so a
    single bad payload doesn't kill the whole album)."""
    created: list[Any] = []
    for m in messages:
        payload = _media_payload(m)
        if payload is None:
            continue
        try:
            attachment = await attachment_service.add(
                task=task, uploader=user, **payload
            )
        except AttachmentServiceError:
            continue
        created.append(attachment)
    return created


@router.message(AttachFileStates.waiting_files, F.document | F.photo)
async def attach_receive(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
    album: list[Message] | None = None,
) -> None:
    data = await state.get_data()
    task_id = int(data["task_id"])
    task = await task_service.get_task(task_id)
    if task is None:
        await message.answer("Задача не найдена.")
        await state.clear()
        return

    messages = album if album else [message]
    created = await _save_attachments_batch(
        task=task,
        user=user,
        messages=messages,
        attachment_service=attachment_service,
    )
    if not created:
        await message.answer("Поддерживаются только документы и фото.")
        return

    recipients = _gather_recipients(task=task, actor=user)
    actor_label = "дизайнер" if user.role == Role.DESIGNER else "заказчик"
    await _broadcast_new_attachments(
        task=task,
        attachments=created,
        recipients=recipients,
        actor_label=actor_label,
        source_messages=messages,
        notifications=notifications,
    )

    suffix = "файл" if len(created) == 1 else "файлов"
    await message.answer(
        f"📎 Добавлено {len(created)} {suffix} к задаче #{task.id}. "
        "Присылайте ещё или /cancel, чтобы завершить."
    )


async def _broadcast_new_attachments(
    *,
    task: Any,
    attachments: list[Any],
    recipients: list[User],
    actor_label: str,
    source_messages: list[Message],
    notifications: NotificationService,
) -> None:
    """Send freshly-uploaded attachments to participants anonymously.

    For a single file we use the old behaviour — copy the message with
    a caption + "Open task" button.  For media groups (multiple
    attachments delivered as an album) we instead push them as an
    album using cached ``file_id`` and follow up with a single
    "context" message that carries the action button.
    """
    if not recipients or not attachments:
        return

    if len(attachments) == 1 and len(source_messages) == 1:
        single = attachments[0]
        head = source_messages[0]
        await notifications.relay_attachment(
            attachment=single,
            recipients=recipients,
            from_chat_id=head.chat.id,
            from_message_id=head.message_id,
            caption=(
                f"📎 Новый файл от <b>{actor_label}</b> "
                f"к задаче #{task.id} — «{task.title}»"
            ),
            task_id=task.id,
        )
        return

    # Album path — one media group + one summary message per recipient.
    for r in recipients:
        await notifications.send_attachments(
            chat_id=r.telegram_id, attachments=attachments
        )
    await notifications.notify_task_event(
        task=task,
        recipients=recipients,
        header=(
            f"📎 {actor_label.capitalize()} прикрепил "
            f"{len(attachments)} файлов"
        ),
    )


# ---------- "Active task" quick-input mode ----------
#
# When a user opens a task card we put them into ``TaskFocus.active``
# with the task id stashed in FSM data.  From that point on, any plain
# message in the chat is routed straight into the task:
#
#   * plain text  → becomes a comment
#   * photo / doc → becomes an attachment
#
# This removes one click + one "send a message…" prompt per comment and
# per file, which is a big QoL win for the most common operations.
#
# Important: we deliberately *do not* intercept reply-keyboard menu
# button presses (BTN_…) or slash-commands here, so the user can still
# navigate away.  Those fall through to the normal menu handlers, and
# any handler that opens a new flow (``/newtask``, "My tasks", etc.)
# clears the state on its own.


async def _focused_task(
    state: FSMContext, task_service: TaskService, user: User
) -> Any | None:
    """Return the task referenced by ``active_task_id`` if the user can
    still see it; otherwise clear the focus state and return ``None``."""
    data = await state.get_data()
    raw_id = data.get("active_task_id")
    if raw_id is None:
        await state.clear()
        return None
    task = await task_service.get_task(int(raw_id))
    if task is None or not task_service.can_view(task, user):
        await state.clear()
        return None
    return task


@router.message(
    TaskFocus.active,
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(ALL_MENU_BUTTONS),
)
async def focused_text_as_comment(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
    notifications: NotificationService,
) -> None:
    task = await _focused_task(state, task_service, user)
    if task is None:
        return  # state cleared; let other handlers / fallback kick in

    text = (message.text or "").strip()
    if not text:
        return

    try:
        comment = await comment_service.add(
            task=task, author=user, text=text
        )
    except CommentServiceError as exc:
        await message.answer(str(exc))
        return

    recipients = _gather_recipients(task=task, actor=user)
    await notifications.notify_new_comment(
        task=task, comment=comment, recipients=recipients
    )
    await message.answer(
        f"💬 Комментарий добавлен к задаче #{task.id}."
    )


@router.message(TaskFocus.active, F.document | F.photo)
async def focused_file_as_attachment(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
    album: list[Message] | None = None,
) -> None:
    task = await _focused_task(state, task_service, user)
    if task is None:
        return

    if not attachment_service.can_attach(task, user):
        await message.answer("У вас нет прав прикреплять файлы к этой задаче.")
        return

    messages = album if album else [message]
    created = await _save_attachments_batch(
        task=task,
        user=user,
        messages=messages,
        attachment_service=attachment_service,
    )
    if not created:
        return

    recipients = _gather_recipients(task=task, actor=user)
    actor_label = "дизайнер" if user.role == Role.DESIGNER else "заказчик"
    await _broadcast_new_attachments(
        task=task,
        attachments=created,
        recipients=recipients,
        actor_label=actor_label,
        source_messages=messages,
        notifications=notifications,
    )

    suffix = "файл" if len(created) == 1 else "файлов"
    await message.answer(
        f"📎 К задаче #{task.id} прикреплено {len(created)} {suffix}."
    )


# ====================================================================
# Edit / delete an existing task
# ====================================================================
#
# Permissions are enforced by :meth:`TaskService.can_edit` /
# :meth:`TaskService.can_delete` — admins and the task's customer can
# both edit metadata and delete the row.  Designers don't get these
# affordances: they collaborate via status transitions and comments.


async def _refresh_card(
    cb: CallbackQuery,
    *,
    task_id: int,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
) -> None:
    """Re-render the task card after an edit. We re-fetch instead of
    using the stale ``task`` instance because update_fields may have
    rewritten any of the displayed columns."""
    task = await task_service.get_task(task_id)
    if task is None or not isinstance(cb.message, Message):
        return
    comments = await comment_service.list_for_task(task.id)
    attachments = await attachment_service.list_for_task(task.id)

    card = format_task_card_for_role(task, viewer_role=user.role)
    lines = [card]
    if attachments:
        lines.append("")
        lines.append(f"<b>📎 Файлов:</b> {len(attachments)}")
    if comments:
        lines.append("")
        lines.append("<b>💬 Комментарии:</b>")
        lines.append(format_comments_timeline(comments))

    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=task_card_keyboard(
            task_id=task.id,
            viewer_role=user.role,
            status=task.status,
            is_assigned=task.designer_id == user.id,
        ),
    )


@router.callback_query(TaskActionCallback.filter(F.action == "edit"))
async def task_edit_open(
    cb: CallbackQuery,
    callback_data: TaskActionCallback,
    user: User,
    task_service: TaskService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return
    if not task_service.can_edit(task, user):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"<b>✏️ Редактирование задачи #{task.id}</b>\n\n"
            "Выберите, что изменить:",
            reply_markup=task_edit_menu_keyboard(task.id),
        )
    await cb.answer()


@router.callback_query(TaskEditCallback.filter(F.field == "title"))
async def task_edit_title_start(
    cb: CallbackQuery,
    callback_data: TaskEditCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not task_service.can_edit(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(EditTaskStates.title)
    await state.update_data(task_id=task.id)
    if isinstance(cb.message, Message):
        await cb.message.answer(
            f"Текущее название:\n<b>{task.title}</b>\n\n"
            "Пришлите новое название (3–200 символов). /cancel — отмена."
        )
    await cb.answer()


@router.message(EditTaskStates.title, F.text)
async def task_edit_title_apply(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    data = await state.get_data()
    task = await task_service.get_task(int(data.get("task_id", 0)))
    if task is None:
        await state.clear()
        await message.answer("Задача не найдена.")
        return
    try:
        updated = await task_service.update_task(
            task, actor=user, title=message.text or ""
        )
    except TaskServiceError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✅ Название задачи #{updated.id} обновлено."
    )
    refreshed = await task_service.get_task(updated.id)
    if refreshed is not None:
        recipients = _gather_recipients(task=refreshed, actor=user)
        await notifications.notify_task_edited(
            task=refreshed,
            changed_fields=["title"],
            recipients=recipients,
        )


@router.callback_query(TaskEditCallback.filter(F.field == "description"))
async def task_edit_desc_start(
    cb: CallbackQuery,
    callback_data: TaskEditCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not task_service.can_edit(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(EditTaskStates.description)
    await state.update_data(task_id=task.id)
    if isinstance(cb.message, Message):
        await cb.message.answer(
            "Текущее описание:\n"
            f"<i>{task.description}</i>\n\n"
            "Пришлите новое описание одним сообщением. /cancel — отмена."
        )
    await cb.answer()


@router.message(EditTaskStates.description, F.text)
async def task_edit_desc_apply(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    data = await state.get_data()
    task = await task_service.get_task(int(data.get("task_id", 0)))
    if task is None:
        await state.clear()
        await message.answer("Задача не найдена.")
        return
    try:
        updated = await task_service.update_task(
            task, actor=user, description=message.text or ""
        )
    except TaskServiceError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✅ Описание задачи #{updated.id} обновлено."
    )
    refreshed = await task_service.get_task(updated.id)
    if refreshed is not None:
        recipients = _gather_recipients(task=refreshed, actor=user)
        await notifications.notify_task_edited(
            task=refreshed,
            changed_fields=["description"],
            recipients=recipients,
        )


@router.callback_query(TaskEditCallback.filter(F.field == "priority"))
async def task_edit_priority_start(
    cb: CallbackQuery,
    callback_data: TaskEditCallback,
    user: User,
    task_service: TaskService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not task_service.can_edit(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Текущий приоритет: <b>{task.priority.label}</b>\n\n"
            "Выберите новый:",
            reply_markup=task_priority_picker(task.id),
        )
    await cb.answer()


@router.callback_query(TaskPriorityCallback.filter())
async def task_edit_priority_apply(
    cb: CallbackQuery,
    callback_data: TaskPriorityCallback,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not task_service.can_edit(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    try:
        new_priority = Priority(callback_data.value)
    except ValueError:
        await cb.answer("Неизвестный приоритет", show_alert=True)
        return
    if new_priority == task.priority:
        await cb.answer("Уже стоит этот приоритет.", show_alert=False)
        await _refresh_card(
            cb,
            task_id=task.id,
            user=user,
            task_service=task_service,
            comment_service=comment_service,
            attachment_service=attachment_service,
        )
        return
    try:
        updated = await task_service.update_task(
            task, actor=user, priority=new_priority
        )
    except TaskServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    await cb.answer(f"Приоритет: {new_priority.label}")
    await _refresh_card(
        cb,
        task_id=updated.id,
        user=user,
        task_service=task_service,
        comment_service=comment_service,
        attachment_service=attachment_service,
    )
    refreshed = await task_service.get_task(updated.id)
    if refreshed is not None:
        recipients = _gather_recipients(task=refreshed, actor=user)
        await notifications.notify_task_edited(
            task=refreshed,
            changed_fields=["priority"],
            recipients=recipients,
        )


# ---------- Deadline edit -------------------------------------------


def _resolve_deadline_preset(preset: str) -> datetime | None:
    """Map a preset token to a concrete UTC datetime.

    All presets land on 18:00 UTC of the target day.  Returns ``None``
    only when the caller meant "clear" (handled separately).
    """
    now = datetime.now(timezone.utc)
    if preset == "today":
        base = now
    elif preset == "tomorrow":
        base = now + timedelta(days=1)
    elif preset == "plus3":
        base = now + timedelta(days=3)
    elif preset == "plus7":
        base = now + timedelta(days=7)
    else:
        return None
    return datetime.combine(base.date(), time(18, 0), tzinfo=timezone.utc)


@router.callback_query(TaskEditCallback.filter(F.field == "deadline"))
async def task_edit_deadline_start(
    cb: CallbackQuery,
    callback_data: TaskEditCallback,
    user: User,
    task_service: TaskService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not task_service.can_edit(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    current = (
        f"<b>{format_dt(task.deadline)}</b>"
        if task.deadline is not None
        else "<i>не задан</i>"
    )
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"Текущий дедлайн: {current}\n\n"
            "Выберите новый или введите вручную:",
            reply_markup=task_deadline_picker(task.id),
        )
    await cb.answer()


@router.callback_query(TaskDeadlineCallback.filter())
async def task_edit_deadline_apply(
    cb: CallbackQuery,
    callback_data: TaskDeadlineCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not task_service.can_edit(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return

    preset = callback_data.preset
    if preset == "manual":
        await state.set_state(EditTaskStates.deadline)
        await state.update_data(task_id=task.id)
        if isinstance(cb.message, Message):
            await cb.message.answer(
                "Введите дату/время в одном из форматов:\n"
                "<code>2026-06-15 18:00</code>\n"
                "<code>15.06.2026 18:00</code>\n"
                "<code>15.06.2026</code>\n\n"
                "/cancel — отмена."
            )
        await cb.answer()
        return

    if preset == "clear":
        try:
            await task_service.update_task(
                task, actor=user, clear_deadline=True
            )
        except TaskServiceError as exc:
            await cb.answer(str(exc), show_alert=True)
            return
        await cb.answer("Дедлайн снят")
    else:
        new_deadline = _resolve_deadline_preset(preset)
        if new_deadline is None:
            await cb.answer("Неизвестный пресет", show_alert=True)
            return
        try:
            await task_service.update_task(
                task, actor=user, deadline=new_deadline
            )
        except TaskServiceError as exc:
            await cb.answer(str(exc), show_alert=True)
            return
        await cb.answer(f"Дедлайн: {format_dt(new_deadline)}")

    await _refresh_card(
        cb,
        task_id=task.id,
        user=user,
        task_service=task_service,
        comment_service=comment_service,
        attachment_service=attachment_service,
    )
    refreshed = await task_service.get_task(task.id)
    if refreshed is not None:
        recipients = _gather_recipients(task=refreshed, actor=user)
        await notifications.notify_task_edited(
            task=refreshed,
            changed_fields=["deadline"],
            recipients=recipients,
        )


@router.message(EditTaskStates.deadline, F.text)
async def task_edit_deadline_manual(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    data = await state.get_data()
    task = await task_service.get_task(int(data.get("task_id", 0)))
    if task is None:
        await state.clear()
        await message.answer("Задача не найдена.")
        return
    parsed = parse_deadline(message.text or "")
    if parsed is None:
        await message.answer(
            "Не удалось распознать дату. Попробуйте формат "
            "<code>2026-06-15 18:00</code>."
        )
        return
    try:
        updated = await task_service.update_task(
            task, actor=user, deadline=parsed
        )
    except TaskServiceError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✅ Дедлайн задачи #{updated.id} установлен: "
        f"<b>{format_dt(parsed)}</b>"
    )
    refreshed = await task_service.get_task(updated.id)
    if refreshed is not None:
        recipients = _gather_recipients(task=refreshed, actor=user)
        await notifications.notify_task_edited(
            task=refreshed,
            changed_fields=["deadline"],
            recipients=recipients,
        )


# ---------- Delete task ---------------------------------------------


@router.callback_query(TaskActionCallback.filter(F.action == "delete"))
async def task_delete_ask(
    cb: CallbackQuery,
    callback_data: TaskActionCallback,
    user: User,
    task_service: TaskService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return
    if not task_service.can_delete(task, user):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"<b>🗑 Удалить задачу?</b>\n\n"
            f"#{task.id} — {task.title}\n\n"
            "<i>Это действие необратимо: будут удалены все комментарии и "
            "файлы задачи.</i>",
            reply_markup=confirm_keyboard(
                action="delete_task", target_id=task.id
            ),
        )
    await cb.answer()


@router.callback_query(ConfirmCallback.filter(F.action == "delete_task"))
async def task_delete_confirm(
    cb: CallbackQuery,
    callback_data: ConfirmCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    notifications: NotificationService,
) -> None:
    task = await task_service.get_task(callback_data.target_id)
    if task is None:
        await cb.answer("Задача не найдена", show_alert=True)
        return

    if not callback_data.yes:
        # Re-render the regular card.
        if isinstance(cb.message, Message):
            await cb.message.edit_text(
                format_task_card_for_role(task, viewer_role=user.role),
                reply_markup=task_card_keyboard(
                    task_id=task.id,
                    viewer_role=user.role,
                    status=task.status,
                    is_assigned=task.designer_id == user.id,
                ),
            )
        await cb.answer("Отменено")
        return

    # Snapshot participants before the row disappears.
    recipients = _gather_recipients(task=task, actor=user)
    task_title = task.title
    task_id = task.id

    try:
        await task_service.delete_task(task, actor=user)
    except TaskServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    # If the deleter was "focused" on this task — drop the focus state.
    current_state = await state.get_state()
    if current_state == TaskFocus.active.state:
        data = await state.get_data()
        if int(data.get("active_task_id", 0) or 0) == task_id:
            await state.clear()

    await notifications.notify_task_deleted(
        task_id=task_id, task_title=task_title, recipients=recipients
    )
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            f"🗑 Задача <b>#{task_id}</b> удалена."
        )
    await cb.answer("Удалено")
