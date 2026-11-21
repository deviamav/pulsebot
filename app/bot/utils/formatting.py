"""Anonymous formatting helpers for tasks and comments.

CRITICAL: none of these helpers ever expose a Telegram username,
Telegram ID or any direct contact handle of another participant.
"""
from __future__ import annotations

from html import escape

from app.db.models import Comment, Role, Task
from app.utils.datetime import format_dt, humanize_delta


def _role_label(role: Role) -> str:
    return role.label


def format_task_short(task: Task, *, viewer_role: Role | None = None) -> str:
    """One-line summary for lists.

    When ``viewer_role`` is :attr:`Role.ADMIN` the summary also reveals
    the customer's name (admins observe both sides). For customers and
    designers we never leak the opposite party — the bot stays anonymous
    between them.
    """
    deadline = format_dt(task.deadline) if task.deadline else "без дедлайна"
    designer = "—"
    if task.designer is not None:
        designer = escape(task.designer.full_name)

    lines: list[str] = [
        f"<b>#{task.id}</b> · {escape(task.title)}",
        f"Статус: <b>{task.status.label}</b> · "
        f"Приоритет: <b>{task.priority.label}</b>",
    ]
    if viewer_role == Role.ADMIN:
        customer = (
            escape(task.customer.full_name) if task.customer else "—"
        )
        lines.append(f"Заказчик: {customer} · Дизайнер: {designer}")
        lines.append(f"Дедлайн: {deadline}")
    else:
        lines.append(f"Дизайнер: {designer} · Дедлайн: {deadline}")

    return "\n".join(lines)


def format_task_card_for_role(task: Task, *, viewer_role: Role) -> str:
    """Detailed task card.

    Depending on ``viewer_role`` reveals either customer or designer name
    (but never both for the opposite side).
    """
    lines: list[str] = [
        f"<b>Задача #{task.id}</b>",
        f"<b>{escape(task.title)}</b>",
        "",
        f"<b>Описание:</b>\n{escape(task.description)}",
        "",
        f"<b>Статус:</b> {task.status.label}",
        f"<b>Приоритет:</b> {task.priority.label}",
    ]
    if task.deadline:
        lines.append(
            f"<b>Дедлайн:</b> {format_dt(task.deadline)} "
            f"({humanize_delta(task.deadline)})"
        )
    else:
        lines.append("<b>Дедлайн:</b> —")
    lines.append(f"<b>Создана:</b> {format_dt(task.created_at)}")
    if task.completed_at:
        lines.append(f"<b>Завершена:</b> {format_dt(task.completed_at)}")

    if viewer_role == Role.ADMIN:
        if task.customer:
            lines.append(f"<b>Заказчик:</b> {escape(task.customer.full_name)}")
        designer_name = task.designer.full_name if task.designer else "—"
        lines.append(f"<b>Дизайнер:</b> {escape(designer_name)}")
    elif viewer_role == Role.CUSTOMER:
        designer_name = (
            task.designer.full_name if task.designer else "не назначен"
        )
        lines.append(f"<b>Исполнитель:</b> {escape(designer_name)}")
    elif viewer_role == Role.DESIGNER:
        lines.append("<b>Заказчик:</b> анонимно")

    return "\n".join(lines)


def format_comment_anonymously(comment: Comment) -> str:
    """Render a comment without leaking the author's identity."""
    return (
        f"<i>{_role_label(comment.author_role)} · "
        f"{format_dt(comment.created_at)}</i>\n"
        f"{escape(comment.text)}"
    )


def format_comments_timeline(comments: list[Comment]) -> str:
    if not comments:
        return "<i>Комментариев пока нет.</i>"
    return "\n\n".join(format_comment_anonymously(c) for c in comments)
