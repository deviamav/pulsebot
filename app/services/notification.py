"""Notification service: anonymous, bot-mediated messaging.

The service is the single point that sends messages back to participants.
It never reveals Telegram usernames, IDs or profile data of the other side.
"""
from __future__ import annotations

from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
)

from app.bot.utils.formatting import (
    format_comment_anonymously,
    format_comments_timeline,
    format_task_card_for_role,
    format_task_short,
)
from app.core.logging import get_logger
from app.db.models import Attachment, Comment, Role, Task, User

logger = get_logger(__name__)


class NotificationService:
    """Sends anonymous notifications via the bot."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def _safe_send(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as exc:
            logger.warning(
                "Failed to send notification",
                chat_id=chat_id,
                error=str(exc),
            )

    async def notify_task_assigned(self, *, task: Task, designer: User) -> None:
        text = (
            "<b>Вам назначена новая задача</b>\n\n"
            + format_task_card_for_role(task, viewer_role=Role.DESIGNER)
        )
        await self._safe_send(chat_id=designer.telegram_id, text=text)

    async def notify_task_unassigned(self, *, designer: User, task: Task) -> None:
        text = (
            "Администратор снял с вас задачу:\n"
            f"<b>#{task.id} — {task.title}</b>"
        )
        await self._safe_send(chat_id=designer.telegram_id, text=text)

    async def notify_task_reassigned_auto(
        self, *, task: Task, new_designer: User, reason: str
    ) -> None:
        """Tell the new owner that a task migrated to them automatically.

        Used after admin actions that drop the previous assignee
        (designer deletion, role change, etc.).  ``reason`` ends up in
        an italic line so the receiver understands why this is a new
        responsibility — not a manual hand-off.
        """
        from html import escape

        text = (
            "<b>📥 На вас переназначена задача</b>\n"
            f"<i>{escape(reason)}</i>\n\n"
            + format_task_card_for_role(task, viewer_role=Role.DESIGNER)
        )
        kb = self._open_task_keyboard(task.id)
        await self._safe_send(
            chat_id=new_designer.telegram_id, text=text, reply_markup=kb
        )

    async def notify_task_unassigned_auto(
        self,
        *,
        task: Task,
        recipients: Iterable[User],
        reason: str,
    ) -> None:
        """Tell participants the task has lost its assignee.

        Triggered when there's no other designer to redistribute to —
        the customer (and possibly other watchers) should know the work
        is parked until an admin assigns someone.
        """
        from html import escape

        text = (
            "<b>⚠️ Задача осталась без исполнителя</b>\n"
            f"<i>{escape(reason)}</i>\n\n"
            f"#{task.id} — {escape(task.title)}\n"
            "Администратор назначит нового дизайнера."
        )
        kb = self._open_task_keyboard(task.id)
        for user in recipients:
            await self._safe_send(
                chat_id=user.telegram_id, text=text, reply_markup=kb
            )

    def _open_task_keyboard(self, task_id: int) -> InlineKeyboardMarkup:
        """Build a single-button "open task" inline keyboard.

        Lives inside the service to avoid a circular import from
        ``app.bot.keyboards``.
        """
        from aiogram.types import InlineKeyboardButton

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🔎 Открыть задачу #{task_id}",
                        callback_data=f"task:open:{task_id}",
                    )
                ]
            ]
        )

    async def notify_task_event(
        self,
        *,
        task: Task,
        recipients: Iterable[User],
        header: str,
    ) -> None:
        """Short follow-up notification with an "Open task" inline button.

        Used after relayed attachments / comments so the recipient
        sees what changed and can jump straight to the task card.
        """
        from html import escape

        text = (
            f"<b>{header}</b>\n\n"
            f"#{task.id} — {escape(task.title)}"
        )
        kb = self._open_task_keyboard(task.id)
        for user in recipients:
            await self._safe_send(
                chat_id=user.telegram_id, text=text, reply_markup=kb
            )

    async def notify_status_change(
        self,
        *,
        task: Task,
        actor_role: Role,
        recipients: Iterable[User],
    ) -> None:
        for user in recipients:
            text = (
                f"<b>Обновлён статус задачи</b>\n\n"
                f"{format_task_short(task)}\n"
                f"<i>Кто изменил:</i> {actor_role.label}\n"
                f"<i>Новый статус:</i> <b>{task.status.label}</b>"
            )
            await self._safe_send(chat_id=user.telegram_id, text=text)

    async def notify_task_card(
        self,
        *,
        task: Task,
        recipient: User,
        attachments: Iterable[Attachment] = (),
        comments: Iterable[Comment] = (),
        header: str | None = None,
        keyboard: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Send a complete task card to a single recipient.

        Used for "actionable" status transitions where the receiver
        must immediately review or react (e.g. WAITING_REVIEW for the
        customer or NEEDS_REVISION for the designer). All attachments
        are re-sent anonymously via the stored ``telegram_file_id`` so
        the recipient sees them right away without opening the task.
        """
        attachments_list = list(attachments)
        comments_list = list(comments)

        lines: list[str] = []
        if header:
            lines.append(f"<b>{header}</b>")
            lines.append("")
        lines.append(format_task_card_for_role(task, viewer_role=recipient.role))
        if attachments_list:
            lines.append("")
            lines.append(
                f"<b>Файлов:</b> {len(attachments_list)} "
                "(приходят отдельными сообщениями ниже)"
            )
        lines.append("")
        lines.append("<b>Комментарии:</b>")
        lines.append(format_comments_timeline(comments_list))

        await self._safe_send(
            chat_id=recipient.telegram_id,
            text="\n".join(lines),
            reply_markup=keyboard,
        )

        # Re-send attachments using cached file_id-s. Group same-type
        # files into media albums for a smoother UX (one notification
        # instead of N).
        await self.send_attachments(
            chat_id=recipient.telegram_id, attachments=attachments_list
        )

    # Maximum items per Telegram media group is 10.
    _MEDIA_GROUP_LIMIT: int = 10

    async def send_attachments(
        self,
        *,
        chat_id: int,
        attachments: Iterable[Attachment],
    ) -> None:
        """Push a collection of attachments to ``chat_id`` anonymously.

        Same-type files are bundled into Telegram media groups (one
        album = one notification on the client). Single items fall back
        to plain ``send_photo`` / ``send_document``.
        """
        photos: list[Attachment] = []
        documents: list[Attachment] = []
        for att in attachments:
            if att.media_type == "photo":
                photos.append(att)
            else:
                documents.append(att)

        await self._send_group(
            chat_id=chat_id,
            attachments=photos,
            media_cls=InputMediaPhoto,
            single_sender="photo",
        )
        await self._send_group(
            chat_id=chat_id,
            attachments=documents,
            media_cls=InputMediaDocument,
            single_sender="document",
        )

    async def _send_group(
        self,
        *,
        chat_id: int,
        attachments: list[Attachment],
        media_cls: type[InputMediaPhoto] | type[InputMediaDocument],
        single_sender: str,
    ) -> None:
        if not attachments:
            return
        if len(attachments) == 1:
            att = attachments[0]
            try:
                if single_sender == "photo":
                    await self._bot.send_photo(
                        chat_id=chat_id, photo=att.telegram_file_id
                    )
                else:
                    await self._bot.send_document(
                        chat_id=chat_id, document=att.telegram_file_id
                    )
            except TelegramAPIError as exc:
                logger.warning(
                    "Failed to send single attachment",
                    chat_id=chat_id,
                    attachment_id=att.id,
                    error=str(exc),
                )
            return

        # Chunk into groups of at most _MEDIA_GROUP_LIMIT items.
        for start in range(0, len(attachments), self._MEDIA_GROUP_LIMIT):
            chunk = attachments[start : start + self._MEDIA_GROUP_LIMIT]
            media = [media_cls(media=att.telegram_file_id) for att in chunk]
            try:
                await self._bot.send_media_group(chat_id=chat_id, media=media)
            except TelegramAPIError as exc:
                logger.warning(
                    "Failed to send media group",
                    chat_id=chat_id,
                    size=len(chunk),
                    error=str(exc),
                )

    async def notify_new_comment(
        self,
        *,
        task: Task,
        comment: Comment,
        recipients: Iterable[User],
    ) -> None:
        body = format_comment_anonymously(comment)
        text = (
            f"<b>💬 Новый комментарий к задаче #{task.id}</b>\n"
            f"<i>{task.title}</i>\n\n"
            f"{body}"
        )
        kb = self._open_task_keyboard(task.id)
        for user in recipients:
            await self._safe_send(
                chat_id=user.telegram_id, text=text, reply_markup=kb
            )

    async def relay_attachment(
        self,
        *,
        attachment: Attachment,
        recipients: Iterable[User],
        from_chat_id: int,
        from_message_id: int,
        caption: str | None = None,
        task_id: int | None = None,
    ) -> None:
        """Relay an uploaded file via ``copyMessage`` so that the
        original sender remains anonymous.

        When ``task_id`` is provided, a "Open task" inline button is
        attached to the copied message so the recipient can react to
        the new file immediately.
        """
        reply_markup = (
            self._open_task_keyboard(task_id) if task_id is not None else None
        )
        for user in recipients:
            try:
                await self._bot.copy_message(
                    chat_id=user.telegram_id,
                    from_chat_id=from_chat_id,
                    message_id=from_message_id,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            except TelegramAPIError as exc:
                logger.warning(
                    "Failed to copy attachment",
                    chat_id=user.telegram_id,
                    attachment_id=attachment.id,
                    error=str(exc),
                )

    async def notify_task_deleted(
        self,
        *,
        task_id: int,
        task_title: str,
        recipients: Iterable[User],
    ) -> None:
        """Inform participants that a task was deleted.

        We accept primitives (not a ``Task`` instance) because by the
        time this is called the row no longer exists in the database.
        """
        from html import escape

        text = (
            "<b>🗑 Задача удалена</b>\n\n"
            f"#{task_id} — {escape(task_title)}"
        )
        for user in recipients:
            await self._safe_send(chat_id=user.telegram_id, text=text)

    async def notify_task_edited(
        self,
        *,
        task: Task,
        changed_fields: Iterable[str],
        recipients: Iterable[User],
    ) -> None:
        """Inform participants that a task's mutable fields changed."""
        fields_ru = {
            "title": "название",
            "description": "описание",
            "priority": "приоритет",
            "deadline": "дедлайн",
        }
        labels = [fields_ru.get(f, f) for f in changed_fields]
        if not labels:
            return
        joined = ", ".join(labels)

        text = (
            f"<b>✏️ Задача обновлена</b>\n\n"
            f"#{task.id} — {task.title}\n"
            f"<i>Изменено:</i> {joined}"
        )
        kb = self._open_task_keyboard(task.id)
        for user in recipients:
            await self._safe_send(
                chat_id=user.telegram_id, text=text, reply_markup=kb
            )

    async def notify_deadline_reminder(
        self, *, task: Task, kind: str, recipients: Iterable[User]
    ) -> None:
        if kind == "24h":
            header = "Напоминание: до дедлайна меньше 24 часов"
        elif kind == "2h":
            header = "Срочно: до дедлайна меньше 2 часов"
        else:
            header = "Просрочено: дедлайн истёк"

        for user in recipients:
            text = (
                f"<b>{header}</b>\n\n"
                f"{format_task_card_for_role(task, viewer_role=user.role)}"
            )
            await self._safe_send(chat_id=user.telegram_id, text=text)
