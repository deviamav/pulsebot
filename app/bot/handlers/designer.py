"""Designer-specific handlers: own task lists."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import RoleFilter
from app.bot.keyboards import (
    PageCallback,
    TaskActionCallback,
    main_menu,
    pagination_keyboard,
)
from app.bot.keyboards.reply import (
    BTN_FINISHED,
    BTN_IN_PROGRESS,
    BTN_MY_TASKS_DESIGNER,
    BTN_NEW_TASKS,
)
from app.bot.utils.formatting import format_task_short
from app.bot.utils.pagination import paginate_meta
from app.core.constants import DEFAULT_PAGE_SIZE
from app.db.models import Role, TaskStatus, User
from app.repositories import TaskFilter
from app.services import TaskService

router = Router(name="designer")
router.message.filter(RoleFilter(Role.DESIGNER))
router.callback_query.filter(RoleFilter(Role.DESIGNER))


@router.message(F.text == BTN_MY_TASKS_DESIGNER)
async def list_my(message: Message, user: User, task_service: TaskService) -> None:
    await _send(
        message,
        user=user,
        scope="d_my",
        flt=TaskFilter(designer_id=user.id),
        task_service=task_service,
    )


@router.message(F.text == BTN_NEW_TASKS)
async def list_new(message: Message, user: User, task_service: TaskService) -> None:
    await _send(
        message,
        user=user,
        scope="d_new",
        flt=TaskFilter(designer_id=user.id, statuses=[TaskStatus.NEW]),
        task_service=task_service,
    )


@router.message(F.text == BTN_IN_PROGRESS)
async def list_in_progress(
    message: Message, user: User, task_service: TaskService
) -> None:
    await _send(
        message,
        user=user,
        scope="d_inprog",
        flt=TaskFilter(
            designer_id=user.id,
            statuses=[
                TaskStatus.IN_PROGRESS,
                TaskStatus.WAITING_REVIEW,
                TaskStatus.NEEDS_REVISION,
            ],
        ),
        task_service=task_service,
    )


@router.message(F.text == BTN_FINISHED)
async def list_finished(
    message: Message, user: User, task_service: TaskService
) -> None:
    if user.role != Role.DESIGNER:
        return
    await _send(
        message,
        user=user,
        scope="d_done",
        flt=TaskFilter(designer_id=user.id, only_finished=True),
        task_service=task_service,
    )


@router.callback_query(
    PageCallback.filter(F.scope.in_({"d_my", "d_new", "d_inprog", "d_done"}))
)
async def paginate(
    cb: CallbackQuery,
    callback_data: PageCallback,
    user: User,
    task_service: TaskService,
) -> None:
    scope = callback_data.scope
    if scope == "d_my":
        flt = TaskFilter(designer_id=user.id)
    elif scope == "d_new":
        flt = TaskFilter(designer_id=user.id, statuses=[TaskStatus.NEW])
    elif scope == "d_inprog":
        flt = TaskFilter(
            designer_id=user.id,
            statuses=[
                TaskStatus.IN_PROGRESS,
                TaskStatus.WAITING_REVIEW,
                TaskStatus.NEEDS_REVISION,
            ],
        )
    else:
        flt = TaskFilter(designer_id=user.id, only_finished=True)

    if isinstance(cb.message, Message):
        text, kb = await _render(
            user=user,
            scope=scope,
            flt=flt,
            task_service=task_service,
            page=callback_data.page,
        )
        if kb is None:
            await cb.message.edit_text(text)
        else:
            await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


async def _send(
    message: Message,
    *,
    user: User,
    scope: str,
    flt: TaskFilter,
    task_service: TaskService,
    page: int = 0,
) -> None:
    text, kb = await _render(
        user=user, scope=scope, flt=flt, task_service=task_service, page=page
    )
    if kb is None:
        await message.answer(text, reply_markup=main_menu(user.role))
    else:
        await message.answer(text, reply_markup=kb)


async def _render(
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
        builder.row(
            *[
                InlineKeyboardButton(text=b.text, callback_data=b.callback_data)
                for b in row
            ]
        )

    return "\n".join(lines), builder.as_markup()
