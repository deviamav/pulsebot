"""Customer handlers: fast task creation FSM and task lists."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import RoleFilter
from app.bot.keyboards import (
    DesignerPickerCallback,
    NewTaskCallback,
    PageCallback,
    TaskActionCallback,
    designer_picker_keyboard,
    main_menu,
    new_task_description_keyboard,
    pagination_keyboard,
)
from app.bot.keyboards.reply import (
    BTN_ACTIVE,
    BTN_FINISHED,
    BTN_MY_TASKS_CUSTOMER,
    BTN_NEW_TASK,
)
from app.bot.states import NewTaskStates
from app.bot.utils.formatting import format_task_short
from app.bot.utils.pagination import paginate_meta
from app.core.constants import DEFAULT_PAGE_SIZE
from app.db.models import Priority, Role, User
from app.repositories import TaskFilter
from app.services import (
    AttachmentService,
    NotificationService,
    TaskService,
    UserService,
)
from app.services.task import TaskServiceError

router = Router(name="customer")
router.message.filter(RoleFilter(Role.CUSTOMER, Role.ADMIN))
router.callback_query.filter(RoleFilter(Role.CUSTOMER, Role.ADMIN))


# ---------- Fast new-task FSM ------------------------------------------
#
# The flow has three logical steps:
#
#   1. title         — one text message
#   2. description   — one or more text/file/album messages, then "Далее"
#   3. designer      — pick assignee (or "Без назначения") → task is
#                      created immediately
#
# Priority defaults to ``MEDIUM`` and deadline is left empty.  Both can
# be tweaked later from the task card.


def _extract_attachment(message: Message) -> dict[str, Any] | None:
    """Convert a single message with a photo/document into a dict that
    can be stored in FSM state until the task is created."""
    if message.document:
        return {
            "telegram_file_id": message.document.file_id,
            "file_unique_id": message.document.file_unique_id,
            "file_name": message.document.file_name,
            "mime_type": message.document.mime_type,
            "media_type": "document",
            "chat_id": message.chat.id,
            "message_id": message.message_id,
        }
    if message.photo:
        photo = message.photo[-1]
        return {
            "telegram_file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_name": None,
            "mime_type": "image/jpeg",
            "media_type": "photo",
            "chat_id": message.chat.id,
            "message_id": message.message_id,
        }
    return None


@router.message(Command("newtask"))
@router.message(F.text == BTN_NEW_TASK)
async def cmd_new_task(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewTaskStates.title)
    await message.answer(
        "<b>🆕 Создание задачи (шаг 1 из 3)</b>\n\n"
        "Введите <b>название</b> задачи (3–200 символов).\n\n"
        "<i>Чтобы отменить — /cancel.</i>"
    )


@router.message(NewTaskStates.title, F.text)
async def step_title(message: Message, state: FSMContext) -> None:
    try:
        title = TaskService.validate_title(message.text or "")
    except TaskServiceError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(title=title, description=None, files=[])
    await state.set_state(NewTaskStates.description)
    await message.answer(
        "<b>📝 Шаг 2 из 3 — описание и файлы</b>\n\n"
        "Опишите задачу одним сообщением. К нему (или отдельно) можно "
        "прикрепить фото и документы — даже альбомом сразу.\n\n"
        "Когда всё добавили — нажмите <b>«➡️ Далее»</b>.",
        reply_markup=new_task_description_keyboard(),
    )


@router.message(NewTaskStates.description, F.text)
async def step_description_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    try:
        validated = TaskService.validate_description(text)
    except TaskServiceError as exc:
        await message.answer(str(exc))
        return

    data = await state.get_data()
    existing = data.get("description") or ""
    description = f"{existing}\n\n{validated}".strip() if existing else validated
    await state.update_data(description=description)
    await message.answer(
        "Описание сохранено. Можно прислать ещё текст или файлы, либо "
        "нажать <b>«➡️ Далее»</b>.",
        reply_markup=new_task_description_keyboard(),
    )


@router.message(NewTaskStates.description, F.document | F.photo)
async def step_description_files(
    message: Message,
    state: FSMContext,
    album: list[Message] | None = None,
) -> None:
    data = await state.get_data()
    files: list[dict[str, Any]] = list(data.get("files", []))

    # Album = single Telegram media-group delivered as one logical batch.
    incoming = album if album else [message]
    added = 0
    for m in incoming:
        extracted = _extract_attachment(m)
        if extracted is not None:
            files.append(extracted)
            added += 1

    # A caption on the first item of an album / single message becomes
    # part of the description if no description has been set yet.
    head = incoming[0]
    caption = (head.caption or "").strip() if head.caption else ""
    if caption and not data.get("description"):
        try:
            description = TaskService.validate_description(caption)
            await state.update_data(description=description)
        except TaskServiceError:
            # Bad caption is non-fatal during attachment step — ignore.
            pass

    await state.update_data(files=files)

    if added == 0:
        await message.answer(
            "Поддерживаются только фото и документы.",
            reply_markup=new_task_description_keyboard(),
        )
        return

    suffix = "файл" if added == 1 else "файлов"
    await message.answer(
        f"📎 Добавлено: {added} {suffix} (всего: {len(files)}).\n"
        "Можно прислать ещё или нажать <b>«➡️ Далее»</b>.",
        reply_markup=new_task_description_keyboard(),
    )


@router.callback_query(
    NewTaskStates.description, NewTaskCallback.filter(F.action == "next")
)
async def step_next_to_designer(
    cb: CallbackQuery, state: FSMContext, user_service: UserService
) -> None:
    data = await state.get_data()
    if not data.get("description") and not data.get("files"):
        await cb.answer(
            "Сначала опишите задачу или прикрепите файлы.",
            show_alert=True,
        )
        return
    if not data.get("description"):
        # Description is mandatory; allow files-only by using the title
        # as a stand-in so the API still gets a non-empty value.
        await state.update_data(description=data.get("title", ""))
    if isinstance(cb.message, Message):
        await _proceed_to_designer(cb.message, state, user_service)
    await cb.answer()


async def _proceed_to_designer(
    message: Message, state: FSMContext, user_service: UserService
) -> None:
    designers = await user_service.list_designers()
    await state.set_state(NewTaskStates.designer)
    if not designers:
        await state.update_data(designer_id=None, designer_name=None)
        await message.answer(
            "<b>👤 Шаг 3 из 3 — исполнитель</b>\n\n"
            "В системе пока нет дизайнеров — задача будет создана без "
            "исполнителя.",
            reply_markup=designer_picker_keyboard(
                [], scope="new", include_skip=True
            ),
        )
        return
    # ``include_auto`` shows the "smart pick" button only when there's
    # more than one designer — otherwise the choice is trivial.
    await message.answer(
        "<b>👤 Шаг 3 из 3 — кому назначить?</b>\n\n"
        "<i>«✨ Авто» подберёт дизайнера с наименьшей текущей нагрузкой "
        "(по активным задачам с учётом приоритета).</i>",
        reply_markup=designer_picker_keyboard(
            designers,
            scope="new",
            include_skip=True,
            include_auto=len(designers) > 1,
        ),
    )


@router.callback_query(
    NewTaskStates.designer, DesignerPickerCallback.filter(F.scope == "new")
)
async def step_designer_pick(
    cb: CallbackQuery,
    callback_data: DesignerPickerCallback,
    state: FSMContext,
    user: User,
    user_service: UserService,
    task_service: TaskService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    designer = await user_service.get_by_id(callback_data.designer_id)
    if designer is None or designer.role != Role.DESIGNER:
        await cb.answer("Дизайнер не найден", show_alert=True)
        return
    await state.update_data(
        designer_id=designer.id, designer_name=designer.full_name
    )
    await _finalize_task_creation(
        cb=cb,
        state=state,
        user=user,
        user_service=user_service,
        task_service=task_service,
        attachment_service=attachment_service,
        notifications=notifications,
    )


@router.callback_query(
    NewTaskStates.designer, NewTaskCallback.filter(F.action == "skip_designer")
)
async def step_designer_skip(
    cb: CallbackQuery,
    state: FSMContext,
    user: User,
    user_service: UserService,
    task_service: TaskService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    await state.update_data(designer_id=None, designer_name=None)
    await _finalize_task_creation(
        cb=cb,
        state=state,
        user=user,
        user_service=user_service,
        task_service=task_service,
        attachment_service=attachment_service,
        notifications=notifications,
    )


@router.callback_query(
    NewTaskStates.designer, NewTaskCallback.filter(F.action == "auto_designer")
)
async def step_designer_auto(
    cb: CallbackQuery,
    state: FSMContext,
    user: User,
    user_service: UserService,
    task_service: TaskService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    """Auto-assign the designer with the lowest current workload.

    Workload = active (non-DONE) task count, with a priority-weighted
    score as a tiebreaker.  See
    :meth:`TaskService.suggest_least_loaded_designer`.
    """
    designers = await user_service.list_designers()
    suggestion = await task_service.suggest_least_loaded_designer(designers)
    if suggestion is None:
        await cb.answer(
            "Не нашлось ни одного дизайнера.", show_alert=True
        )
        return

    designer, _weighted = suggestion
    await state.update_data(
        designer_id=designer.id, designer_name=designer.full_name
    )
    # Brief toast — the recipient will also be visible in the
    # "Задача создана" summary that comes right after.
    await cb.answer(
        f"Назначаем: {designer.full_name}", show_alert=False
    )
    await _finalize_task_creation(
        cb=cb,
        state=state,
        user=user,
        user_service=user_service,
        task_service=task_service,
        attachment_service=attachment_service,
        notifications=notifications,
    )


@router.callback_query(NewTaskCallback.filter(F.action == "cancel"))
async def flow_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(cb.message, Message):
        await cb.message.edit_text("Создание задачи отменено.")
    await cb.answer()


@router.callback_query(
    NewTaskStates.designer, NewTaskCallback.filter(F.action == "back")
)
async def flow_back_to_description(
    cb: CallbackQuery, state: FSMContext
) -> None:
    """Hop from the designer picker back to the description step
    without losing the data the user has already entered."""
    await state.set_state(NewTaskStates.description)
    if isinstance(cb.message, Message):
        await cb.message.edit_text(
            "<b>📝 Шаг 2 из 3 — описание и файлы</b>\n\n"
            "Опишите задачу одним сообщением. К нему (или отдельно) можно "
            "прикрепить фото и документы — даже альбомом сразу.\n\n"
            "Когда всё добавили — нажмите <b>«➡️ Далее»</b>.",
            reply_markup=new_task_description_keyboard(),
        )
    await cb.answer()


async def _finalize_task_creation(
    *,
    cb: CallbackQuery,
    state: FSMContext,
    user: User,
    user_service: UserService,
    task_service: TaskService,
    attachment_service: AttachmentService,
    notifications: NotificationService,
) -> None:
    """Persist the task collected in FSM state and notify the designer."""
    data = await state.get_data()
    designer_id = data.get("designer_id")
    designer = (
        await user_service.get_by_id(designer_id) if designer_id else None
    )

    try:
        task = await task_service.create_task(
            title=data["title"],
            description=data.get("description") or data["title"],
            priority=Priority.MEDIUM,
            customer=user,
            designer=designer,
            deadline=None,
        )
    except TaskServiceError as exc:
        await cb.answer(str(exc), show_alert=True)
        return

    files: list[dict[str, Any]] = data.get("files", [])
    for f in files:
        attachment = await attachment_service.add(
            task=task,
            uploader=user,
            telegram_file_id=f["telegram_file_id"],
            media_type=f["media_type"],
            file_name=f.get("file_name"),
            mime_type=f.get("mime_type"),
            file_unique_id=f.get("file_unique_id"),
        )
        if designer is not None:
            await notifications.relay_attachment(
                attachment=attachment,
                recipients=[designer],
                from_chat_id=f["chat_id"],
                from_message_id=f["message_id"],
                caption=f"📎 Файл к задаче #{task.id} — «{task.title}»",
                task_id=task.id,
            )

    if designer is not None:
        await notifications.notify_task_assigned(task=task, designer=designer)

    await state.clear()

    summary_lines = [
        f"<b>✅ Задача #{task.id} создана</b>",
        "",
        f"<b>Название:</b> {task.title}",
    ]
    if designer is not None:
        summary_lines.append(f"<b>Исполнитель:</b> {designer.full_name}")
    else:
        summary_lines.append("<b>Исполнитель:</b> не назначен")
    if files:
        summary_lines.append(f"<b>Файлов прикреплено:</b> {len(files)}")
    summary_lines.append("")
    summary_lines.append(
        "<i>Приоритет и дедлайн можно поменять из карточки задачи.</i>"
    )

    if isinstance(cb.message, Message):
        await cb.message.edit_text("\n".join(summary_lines))
    await cb.answer("Готово")


# ---------- Task lists ----------


@router.message(F.text == BTN_MY_TASKS_CUSTOMER)
async def list_my_tasks(message: Message, user: User, task_service: TaskService) -> None:
    await _send_task_list(
        message,
        user=user,
        scope="my",
        flt=TaskFilter(customer_id=user.id),
        task_service=task_service,
    )


@router.message(F.text == BTN_ACTIVE)
async def list_active(message: Message, user: User, task_service: TaskService) -> None:
    if user.role != Role.CUSTOMER:
        return
    await _send_task_list(
        message,
        user=user,
        scope="active",
        flt=TaskFilter(customer_id=user.id, only_active=True),
        task_service=task_service,
    )


@router.message(F.text == BTN_FINISHED)
async def list_finished_customer(
    message: Message, user: User, task_service: TaskService
) -> None:
    if user.role != Role.CUSTOMER:
        return
    await _send_task_list(
        message,
        user=user,
        scope="finished_c",
        flt=TaskFilter(customer_id=user.id, only_finished=True),
        task_service=task_service,
    )


@router.callback_query(PageCallback.filter(F.scope.in_({"my", "active", "finished_c"})))
async def paginate_customer(
    cb: CallbackQuery,
    callback_data: PageCallback,
    user: User,
    task_service: TaskService,
) -> None:
    scope = callback_data.scope
    if scope == "my":
        flt = TaskFilter(customer_id=user.id)
    elif scope == "active":
        flt = TaskFilter(customer_id=user.id, only_active=True)
    else:
        flt = TaskFilter(customer_id=user.id, only_finished=True)

    if isinstance(cb.message, Message):
        await _edit_task_list(
            cb.message,
            user=user,
            scope=scope,
            flt=flt,
            task_service=task_service,
            page=callback_data.page,
        )
    await cb.answer()


async def _send_task_list(
    message: Message,
    *,
    user: User,
    scope: str,
    flt: TaskFilter,
    task_service: TaskService,
    page: int = 0,
) -> None:
    text, kb = await _render_task_list(
        user=user, scope=scope, flt=flt, task_service=task_service, page=page
    )
    if kb is None:
        await message.answer(text, reply_markup=main_menu(user.role))
    else:
        await message.answer(text, reply_markup=kb)


async def _edit_task_list(
    message: Message,
    *,
    user: User,
    scope: str,
    flt: TaskFilter,
    task_service: TaskService,
    page: int,
) -> None:
    text, kb = await _render_task_list(
        user=user, scope=scope, flt=flt, task_service=task_service, page=page
    )
    if kb is None:
        await message.edit_text(text)
    else:
        await message.edit_text(text, reply_markup=kb)


async def _render_task_list(
    *,
    user: User,
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
        lines.append(format_task_short(t))
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
        builder.row(*[InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row])

    return "\n".join(lines), builder.as_markup()
