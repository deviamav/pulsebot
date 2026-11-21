"""Deadline reminder scheduler.

Lightweight asyncio loop that periodically scans the DB for tasks
that need a reminder and pushes notifications via :class:`NotificationService`.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.core.constants import (
    REMINDER_24H_BEFORE_SECONDS,
    REMINDER_2H_BEFORE_SECONDS,
)
from app.core.logging import get_logger
from app.db.session import session_scope
from app.repositories import TaskRepository
from app.services.notification import NotificationService
from app.utils.datetime import utcnow

logger = get_logger(__name__)


class ReminderScheduler:
    """Periodic reminder scanner."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        notifications: NotificationService,
        interval_seconds: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._notifications = notifications
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="reminder-scheduler")
        logger.info("Reminder scheduler started", interval_s=self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Reminder scheduler stopped")

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Reminder tick failed", error=str(exc))
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._interval
                )
            except asyncio.TimeoutError:
                continue
            else:
                break

    async def _tick(self) -> None:
        now = utcnow()
        lookahead_24h = now + timedelta(seconds=REMINDER_24H_BEFORE_SECONDS)
        lookahead_2h = now + timedelta(seconds=REMINDER_2H_BEFORE_SECONDS)

        async with session_scope(self._sessionmaker) as session:
            task_repo = TaskRepository(session)

            tasks = await task_repo.fetch_due_for_reminders(
                now=now,
                lookahead_24h=lookahead_24h,
                lookahead_2h=lookahead_2h,
            )
            if not tasks:
                return

            for task in tasks:
                if task.deadline is None:
                    continue

                # Reminders go only to direct participants. Admins
                # monitor deadlines via the statistics screen.
                recipients = []
                if task.customer:
                    recipients.append(task.customer)
                if task.designer:
                    recipients.append(task.designer)
                if not recipients:
                    continue

                if task.deadline <= now and not task.reminder_overdue_sent:
                    await self._notifications.notify_deadline_reminder(
                        task=task, kind="overdue", recipients=recipients
                    )
                    await task_repo.mark_reminder_sent(task.id, kind="overdue")
                    continue

                if task.deadline <= lookahead_2h and not task.reminder_2h_sent:
                    await self._notifications.notify_deadline_reminder(
                        task=task, kind="2h", recipients=recipients
                    )
                    await task_repo.mark_reminder_sent(task.id, kind="2h")
                    continue

                if task.deadline <= lookahead_24h and not task.reminder_24h_sent:
                    await self._notifications.notify_deadline_reminder(
                        task=task, kind="24h", recipients=recipients
                    )
                    await task_repo.mark_reminder_sent(task.id, kind="24h")
