"""Task service: business logic for task lifecycle."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final

from app.core.constants import (
    TASK_DESCRIPTION_MAX_LENGTH,
    TASK_DESCRIPTION_MIN_LENGTH,
    TASK_TITLE_MAX_LENGTH,
    TASK_TITLE_MIN_LENGTH,
)
from app.core.logging import get_logger
from app.db.models import Priority, Role, Task, TaskStatus, User
from app.repositories import TaskFilter, TaskRepository

logger = get_logger(__name__)


_ALLOWED_TRANSITIONS: Final[dict[TaskStatus, set[TaskStatus]]] = {
    TaskStatus.NEW: {TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.WAITING_REVIEW},
    TaskStatus.WAITING_REVIEW: {
        TaskStatus.NEEDS_REVISION,
        TaskStatus.DONE,
    },
    TaskStatus.NEEDS_REVISION: {TaskStatus.IN_PROGRESS},
    TaskStatus.DONE: set(),
}


class TaskServiceError(Exception):
    """Domain-level error in :class:`TaskService`."""


class TaskService:
    """Encapsulates task lifecycle logic."""

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    @staticmethod
    def validate_title(title: str) -> str:
        title = title.strip()
        if not (TASK_TITLE_MIN_LENGTH <= len(title) <= TASK_TITLE_MAX_LENGTH):
            raise TaskServiceError(
                f"Название задачи должно содержать {TASK_TITLE_MIN_LENGTH}–"
                f"{TASK_TITLE_MAX_LENGTH} символов."
            )
        return title

    @staticmethod
    def validate_description(description: str) -> str:
        description = description.strip()
        if not (
            TASK_DESCRIPTION_MIN_LENGTH <= len(description) <= TASK_DESCRIPTION_MAX_LENGTH
        ):
            raise TaskServiceError(
                f"Описание задачи должно содержать {TASK_DESCRIPTION_MIN_LENGTH}–"
                f"{TASK_DESCRIPTION_MAX_LENGTH} символов."
            )
        return description

    async def create_task(
        self,
        *,
        title: str,
        description: str,
        priority: Priority,
        customer: User,
        designer: User | None,
        deadline: datetime | None,
    ) -> Task:
        """Create a new task with full validation."""
        title = self.validate_title(title)
        description = self.validate_description(description)

        if customer.role != Role.CUSTOMER and customer.role != Role.ADMIN:
            raise TaskServiceError("Создавать задачи могут только заказчики.")
        if designer is not None and designer.role != Role.DESIGNER:
            raise TaskServiceError("Назначенный исполнитель не является дизайнером.")

        task = await self._repo.create(
            title=title,
            description=description,
            priority=priority,
            customer_id=customer.id,
            designer_id=designer.id if designer else None,
            deadline=deadline,
        )
        logger.info(
            "Task created",
            task_id=task.id,
            customer_id=customer.id,
            designer_id=task.designer_id,
            priority=priority.value,
        )
        return task

    async def get_task(self, task_id: int, *, with_relations: bool = True) -> Task | None:
        return await self._repo.get_by_id(task_id, with_relations=with_relations)

    def can_view(self, task: Task, user: User) -> bool:
        if user.role == Role.ADMIN:
            return True
        if user.role == Role.CUSTOMER and task.customer_id == user.id:
            return True
        if user.role == Role.DESIGNER and task.designer_id == user.id:
            return True
        return False

    def can_change_status(self, task: Task, user: User, new_status: TaskStatus) -> bool:
        if not self.can_view(task, user):
            return False
        if new_status not in _ALLOWED_TRANSITIONS.get(task.status, set()):
            return False

        if user.role == Role.ADMIN:
            return True

        if user.role == Role.DESIGNER:
            return new_status in {
                TaskStatus.IN_PROGRESS,
                TaskStatus.WAITING_REVIEW,
            }

        if user.role == Role.CUSTOMER:
            return new_status in {
                TaskStatus.DONE,
                TaskStatus.NEEDS_REVISION,
            }

        return False

    async def change_status(
        self, task: Task, *, new_status: TaskStatus, actor: User
    ) -> Task:
        if not self.can_change_status(task, actor, new_status):
            raise TaskServiceError("Недостаточно прав или запрещённый переход статуса.")
        updated = await self._repo.update_status(task.id, new_status)
        if updated is None:
            raise TaskServiceError("Задача не найдена.")
        logger.info(
            "Task status changed",
            task_id=task.id,
            new_status=new_status.value,
            actor_id=actor.id,
            actor_role=actor.role.value,
        )
        return updated

    # ---- Edit / delete authorisation -----------------------------------

    def can_edit(self, task: Task, user: User) -> bool:
        """Who is allowed to edit a task's mutable fields (title, body,
        priority, deadline).

        * Admin   — any task.
        * Customer — only their own.
        * Designer — never (they collaborate via status / comments).
        """
        if user.role == Role.ADMIN:
            return True
        if user.role == Role.CUSTOMER and task.customer_id == user.id:
            return True
        return False

    def can_delete(self, task: Task, user: User) -> bool:
        """Same matrix as :meth:`can_edit`."""
        return self.can_edit(task, user)

    async def update_task(
        self,
        task: Task,
        *,
        actor: User,
        title: str | None = None,
        description: str | None = None,
        priority: Priority | None = None,
        deadline: datetime | None = None,
        clear_deadline: bool = False,
    ) -> Task:
        """Apply a partial edit. Raises :class:`TaskServiceError` for
        any validation or permission failure."""
        if not self.can_edit(task, actor):
            raise TaskServiceError("Недостаточно прав для редактирования задачи.")

        if title is not None:
            title = self.validate_title(title)
        if description is not None:
            description = self.validate_description(description)

        updated = await self._repo.update_fields(
            task.id,
            title=title,
            description=description,
            priority=priority,
            deadline=deadline,
            clear_deadline=clear_deadline,
        )
        if updated is None:
            raise TaskServiceError("Задача не найдена.")
        logger.info(
            "Task updated",
            task_id=task.id,
            actor_id=actor.id,
            fields=[
                k
                for k, v in (
                    ("title", title),
                    ("description", description),
                    ("priority", priority),
                    ("deadline", deadline),
                    ("clear_deadline", clear_deadline or None),
                )
                if v is not None
            ],
        )
        return updated

    async def delete_task(self, task: Task, *, actor: User) -> None:
        """Hard-delete a task (cascades to comments and attachments)."""
        if not self.can_delete(task, actor):
            raise TaskServiceError("Недостаточно прав для удаления задачи.")
        ok = await self._repo.delete(task.id)
        if not ok:
            raise TaskServiceError("Задача не найдена.")
        logger.info("Task deleted", task_id=task.id, actor_id=actor.id)

    async def reassign_designer(
        self, task: Task, *, designer: User | None, actor: User
    ) -> Task:
        if actor.role != Role.ADMIN:
            raise TaskServiceError("Переназначить дизайнера может только администратор.")
        if designer is not None and designer.role != Role.DESIGNER:
            raise TaskServiceError("Пользователь не является дизайнером.")
        updated = await self._repo.reassign_designer(
            task.id, designer.id if designer else None
        )
        if updated is None:
            raise TaskServiceError("Задача не найдена.")
        logger.info(
            "Task reassigned",
            task_id=task.id,
            new_designer_id=updated.designer_id,
            actor_id=actor.id,
        )
        return updated

    async def list_paginated(
        self,
        flt: TaskFilter,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Task], int]:
        return await self._repo.list_paginated(flt, page=page, page_size=page_size)

    async def stats(self) -> dict[TaskStatus, int]:
        return await self._repo.stats()

    async def stats_by_designer(self) -> list[tuple[User, dict[TaskStatus, int]]]:
        return await self._repo.stats_by_designer()

    async def stats_by_customer(self) -> list[tuple[User, dict[TaskStatus, int]]]:
        return await self._repo.stats_by_customer()

    async def overdue_count(self) -> int:
        from app.utils.datetime import utcnow

        return await self._repo.overdue_count(now=utcnow())

    async def list_active_for_designer(self, designer_id: int) -> list[Task]:
        """All non-DONE tasks currently assigned to a designer."""
        return await self._repo.list_active_by_designer(designer_id)

    async def count_active_for_designer(self, designer_id: int) -> int:
        """How many non-DONE tasks the designer currently owns."""
        return await self._repo.count_active_by_designer(designer_id)

    async def redistribute_designer_tasks(
        self,
        *,
        departing: User,
        candidates: Sequence[User],
    ) -> list[tuple[Task, User | None]]:
        """Move a designer's active tasks to the rest of the team.

        Picks the least-loaded eligible designer per task (priority
        DESC so urgent tasks go to the freshest designer first). Local
        workload counters are incremented as we go to keep the
        distribution balanced across the batch.

        When ``candidates`` is empty, tasks are simply un-assigned
        (``designer_id`` becomes ``NULL``).  Returns the list of
        ``(task, new_designer | None)`` pairs so the caller can fan out
        notifications.
        """
        tasks = await self._repo.list_active_by_designer(departing.id)
        if not tasks:
            return []

        eligible = [
            d
            for d in candidates
            if d.role == Role.DESIGNER
            and d.is_active
            and d.id != departing.id
        ]

        load_map: dict[int, tuple[int, int]] = {}
        if eligible:
            raw = await self._repo.designer_workload()
            raw.pop(departing.id, None)
            for d in eligible:
                load_map[d.id] = raw.get(d.id, (0, 0))

        weights = {Priority.LOW: 1, Priority.MEDIUM: 2, Priority.HIGH: 3}

        results: list[tuple[Task, User | None]] = []
        for task in tasks:
            new_designer: User | None = None
            if eligible:
                new_designer = min(
                    eligible,
                    key=lambda d: (
                        load_map[d.id][0],
                        load_map[d.id][1],
                        d.id,
                    ),
                )
                cnt, weight = load_map[new_designer.id]
                load_map[new_designer.id] = (
                    cnt + 1,
                    weight + weights.get(task.priority, 2),
                )

            await self._repo.reassign_designer(
                task.id, new_designer.id if new_designer else None
            )
            results.append((task, new_designer))
            logger.info(
                "Task redistributed",
                task_id=task.id,
                old_designer_id=departing.id,
                new_designer_id=new_designer.id if new_designer else None,
            )
        return results

    async def suggest_least_loaded_designer(
        self, designers: Sequence[User]
    ) -> tuple[User, int] | None:
        """Pick the designer with the lowest current workload.

        Workload is measured over *active* (non-DONE) tasks and a
        priority-weighted score is used as the tiebreaker:

            primary key : open task count       (ascending)
            secondary   : priority-weighted load (ascending)
            tertiary    : user id               (stable ordering)

        Designers without any open tasks have load ``(0, 0)`` and win
        immediately.  Returns ``(designer, weighted_load)`` or ``None``
        when the input list is empty.
        """
        if not designers:
            return None
        load_map = await self._repo.designer_workload()
        ranked = sorted(
            designers,
            key=lambda d: (
                load_map.get(d.id, (0, 0))[0],
                load_map.get(d.id, (0, 0))[1],
                d.id,
            ),
        )
        winner = ranked[0]
        _count, weighted = load_map.get(winner.id, (0, 0))
        return winner, weighted
