"""Comment-related handlers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters import RoleFilter
from app.bot.keyboards import TaskActionCallback
from app.bot.states import CommentStates
from app.db.models import Role, User
from app.services import (
    CommentService,
    NotificationService,
    TaskService,
)
from app.services.comment import CommentServiceError

router = Router(name="comments")
router.message.filter(RoleFilter(Role.ADMIN, Role.CUSTOMER, Role.DESIGNER))
router.callback_query.filter(RoleFilter(Role.ADMIN, Role.CUSTOMER, Role.DESIGNER))


@router.callback_query(TaskActionCallback.filter(F.action == "comment"))
async def start_comment(
    cb: CallbackQuery,
    callback_data: TaskActionCallback,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
) -> None:
    task = await task_service.get_task(callback_data.task_id)
    if task is None or not comment_service.can_comment(task, user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(CommentStates.waiting_text)
    await state.update_data(task_id=task.id)
    if isinstance(cb.message, Message):
        await cb.message.answer(
            f"Напишите комментарий к задаче #{task.id}. Чтобы отменить: /cancel"
        )
    await cb.answer()


@router.message(CommentStates.waiting_text, F.text)
async def receive_comment(
    message: Message,
    state: FSMContext,
    user: User,
    task_service: TaskService,
    comment_service: CommentService,
    notifications: NotificationService,
) -> None:
    data = await state.get_data()
    task_id = int(data["task_id"])
    task = await task_service.get_task(task_id)
    if task is None:
        await message.answer("Задача не найдена.")
        await state.clear()
        return

    try:
        comment = await comment_service.add(
            task=task, author=user, text=message.text or ""
        )
    except CommentServiceError as exc:
        await message.answer(str(exc))
        return

    # Notify only the opposite participant. Admins observe via the
    # statistics screen and "All tasks" listing — they don't get
    # live notifications on every comment.
    recipients: list[User] = []
    if task.customer is not None and task.customer.id != user.id:
        recipients.append(task.customer)
    if task.designer is not None and task.designer.id != user.id:
        recipients.append(task.designer)

    await notifications.notify_new_comment(
        task=task, comment=comment, recipients=recipients
    )

    await state.clear()
    await message.answer("Комментарий отправлен.")
