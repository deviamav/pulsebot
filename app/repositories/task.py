"""Task repository with filtering and pagination support."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.db.models import Priority, Task, TaskStatus, User
from app.repositories.base import BaseRepository


@dataclass(slots=True)
class TaskFilter:
    """Filter criteria for task listing."""

    customer_id: int | None = None
    designer_id: int | None = None
    statuses: list[TaskStatus] = field(default_factory=list)
    priorities: list[Priority] = field(default_factory=list)
    only_active: bool = False
    only_finished: bool = False


class TaskRepository(BaseRepository):
    """Persistence operations for tasks."""

    @staticmethod
    def _apply_filter(stmt: Select[tuple[Task]], f: TaskFilter) -> Select[tuple[Task]]:
        if f.customer_id is not None:
            stmt = stmt.where(Task.customer_id == f.customer_id)
        if f.designer_id is not None:
            stmt = stmt.where(Task.designer_id == f.designer_id)
        if f.statuses:
            stmt = stmt.where(Task.status.in_(f.statuses))
        if f.priorities:
            stmt = stmt.where(Task.priority.in_(f.priorities))
        if f.only_active:
            stmt = stmt.where(
                Task.status.in_(
                    [
                        TaskStatus.NEW,
                        TaskStatus.IN_PROGRESS,
                        TaskStatus.WAITING_REVIEW,
                        TaskStatus.NEEDS_REVISION,
                    ]
                )
            )
        if f.only_finished:
            stmt = stmt.where(Task.status == TaskStatus.DONE)
        return stmt

    async def create(
        self,
        *,
        title: str,
        description: str,
        priority: Priority,
        customer_id: int,
        designer_id: int | None,
        deadline: datetime | None,
    ) -> Task:
        task = Task(
            title=title,
            description=description,
            priority=priority,
            status=TaskStatus.NEW,
            customer_id=customer_id,
            designer_id=designer_id,
            deadline=deadline,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_by_id(self, task_id: int, *, with_relations: bool = False) -> Task | None:
        stmt = select(Task).where(Task.id == task_id)
        if with_relations:
            stmt = stmt.options(
                selectinload(Task.customer),
                selectinload(Task.designer),
                selectinload(Task.comments),
                selectinload(Task.attachments),
            )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, task_id: int, status: TaskStatus) -> Task | None:
        task = await self.session.get(Task, task_id)
        if task is None:
            return None
        task.status = status
        if status is TaskStatus.DONE and task.completed_at is None:
            task.completed_at = datetime.utcnow()
        if status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS, TaskStatus.NEEDS_REVISION}:
            task.completed_at = None
        await self.session.flush()
        return task

    async def update_fields(
        self,
        task_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: Priority | None = None,
        deadline: datetime | None = None,
        clear_deadline: bool = False,
    ) -> Task | None:
        """Partial-update mutable fields of a task.

        ``None`` arguments mean "leave the column as is".  To clear a
        deadline pass ``clear_deadline=True`` (``deadline=None`` alone
        is ambiguous because ``None`` is also the "no change" sentinel).

        Resets the reminder flags whenever the deadline changes so that
        the scheduler picks the task up again with the new schedule.
        """
        task = await self.session.get(Task, task_id)
        if task is None:
            return None
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if priority is not None:
            task.priority = priority
        if clear_deadline:
            task.deadline = None
            task.reminder_24h_sent = False
            task.reminder_2h_sent = False
            task.reminder_overdue_sent = False
        elif deadline is not None:
            task.deadline = deadline
            task.reminder_24h_sent = False
            task.reminder_2h_sent = False
            task.reminder_overdue_sent = False
        await self.session.flush()
        return task

    async def delete(self, task_id: int) -> bool:
        """Delete a task. Returns ``True`` if a row was removed.

        Attachments and comments are removed by FK ``ON DELETE CASCADE``.
        """
        task = await self.session.get(Task, task_id)
        if task is None:
            return False
        await self.session.delete(task)
        await self.session.flush()
        return True

    async def count_active_by_designer(self, designer_id: int) -> int:
        """Cheap count of non-DONE tasks assigned to a designer."""
        active_statuses = [
            TaskStatus.NEW,
            TaskStatus.IN_PROGRESS,
            TaskStatus.WAITING_REVIEW,
            TaskStatus.NEEDS_REVISION,
        ]
        stmt = select(func.count(Task.id)).where(
            Task.designer_id == designer_id,
            Task.status.in_(active_statuses),
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def list_active_by_designer(
        self, designer_id: int, *, with_relations: bool = True
    ) -> list[Task]:
        """All non-DONE tasks assigned to a designer.

        Used to migrate workload to other designers before a hard
        delete of the assignee.  Relations are eager-loaded by default
        so the caller can immediately send notifications without
        triggering lazy I/O.
        """
        active_statuses = [
            TaskStatus.NEW,
            TaskStatus.IN_PROGRESS,
            TaskStatus.WAITING_REVIEW,
            TaskStatus.NEEDS_REVISION,
        ]
        stmt = select(Task).where(
            Task.designer_id == designer_id,
            Task.status.in_(active_statuses),
        )
        if with_relations:
            stmt = stmt.options(
                selectinload(Task.customer), selectinload(Task.designer)
            )
        stmt = stmt.order_by(Task.priority.desc(), Task.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def reassign_designer(self, task_id: int, designer_id: int | None) -> Task | None:
        task = await self.session.get(Task, task_id)
        if task is None:
            return None
        task.designer_id = designer_id
        task.reminder_24h_sent = False
        task.reminder_2h_sent = False
        task.reminder_overdue_sent = False
        await self.session.flush()
        return task

    async def list_paginated(
        self,
        flt: TaskFilter,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Task], int]:
        base = self._apply_filter(select(Task), flt)
        total_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(total_stmt)).scalar_one()

        stmt = (
            base.options(selectinload(Task.designer), selectinload(Task.customer))
            .order_by(Task.created_at.desc())
            .limit(page_size)
            .offset(page * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def mark_reminder_sent(self, task_id: int, *, kind: str) -> None:
        task = await self.session.get(Task, task_id)
        if task is None:
            return
        if kind == "24h":
            task.reminder_24h_sent = True
        elif kind == "2h":
            task.reminder_2h_sent = True
        elif kind == "overdue":
            task.reminder_overdue_sent = True
        await self.session.flush()

    async def fetch_due_for_reminders(
        self, *, now: datetime, lookahead_24h: datetime, lookahead_2h: datetime
    ) -> list[Task]:
        """Return active tasks that might need a reminder right now."""
        stmt = (
            select(Task)
            .where(
                Task.deadline.is_not(None),
                Task.status.in_(
                    [
                        TaskStatus.NEW,
                        TaskStatus.IN_PROGRESS,
                        TaskStatus.WAITING_REVIEW,
                        TaskStatus.NEEDS_REVISION,
                    ]
                ),
                or_(
                    (Task.reminder_24h_sent.is_(False)) & (Task.deadline <= lookahead_24h),
                    (Task.reminder_2h_sent.is_(False)) & (Task.deadline <= lookahead_2h),
                    (Task.reminder_overdue_sent.is_(False)) & (Task.deadline <= now),
                ),
            )
            .options(selectinload(Task.customer), selectinload(Task.designer))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def stats(self) -> dict[TaskStatus, int]:
        stmt = select(Task.status, func.count(Task.id)).group_by(Task.status)
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

    async def stats_by_designer(self) -> list[tuple[User, dict[TaskStatus, int]]]:
        return await self._stats_grouped(by="designer")

    async def stats_by_customer(self) -> list[tuple[User, dict[TaskStatus, int]]]:
        return await self._stats_grouped(by="customer")

    async def _stats_grouped(
        self, *, by: str
    ) -> list[tuple[User, dict[TaskStatus, int]]]:
        column = Task.designer_id if by == "designer" else Task.customer_id
        stmt = (
            select(User, Task.status, func.count(Task.id))
            .join(Task, column == User.id)
            .group_by(User.id, Task.status)
            .order_by(User.full_name)
        )
        result = await self.session.execute(stmt)

        buckets: dict[int, tuple[User, dict[TaskStatus, int]]] = {}
        for user, status, count in result.all():
            entry = buckets.setdefault(user.id, (user, {}))
            entry[1][status] = int(count)
        return list(buckets.values())

    async def designer_workload(self) -> dict[int, tuple[int, int]]:
        """Per-designer workload over active (non-DONE) tasks.

        Returns a mapping ``{designer_id: (count, weighted)}`` where:

        * ``count``     — number of active tasks
        * ``weighted``  — sum of priority weights (HIGH=3, MEDIUM=2,
          LOW=1), used as a tiebreaker so urgent work counts heavier
          than backlog grooming.

        Designers without any active tasks won't appear in the map —
        callers should treat them as load ``(0, 0)``.
        """
        active_statuses = [
            TaskStatus.NEW,
            TaskStatus.IN_PROGRESS,
            TaskStatus.WAITING_REVIEW,
            TaskStatus.NEEDS_REVISION,
        ]
        stmt = (
            select(Task.designer_id, Task.priority, func.count(Task.id))
            .where(
                Task.designer_id.is_not(None),
                Task.status.in_(active_statuses),
            )
            .group_by(Task.designer_id, Task.priority)
        )
        weights: dict[Priority, int] = {
            Priority.LOW: 1,
            Priority.MEDIUM: 2,
            Priority.HIGH: 3,
        }
        result = await self.session.execute(stmt)
        load: dict[int, tuple[int, int]] = {}
        for designer_id, priority, count in result.all():
            count_int = int(count)
            weighted = weights.get(priority, 2) * count_int
            prev_count, prev_weight = load.get(designer_id, (0, 0))
            load[designer_id] = (
                prev_count + count_int,
                prev_weight + weighted,
            )
        return load

    async def overdue_count(self, *, now: datetime) -> int:
        """Count active tasks past their deadline."""
        stmt = (
            select(func.count(Task.id))
            .where(
                Task.deadline.is_not(None),
                Task.deadline < now,
                Task.status.in_(
                    [
                        TaskStatus.NEW,
                        TaskStatus.IN_PROGRESS,
                        TaskStatus.WAITING_REVIEW,
                        TaskStatus.NEEDS_REVISION,
                    ]
                ),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)
