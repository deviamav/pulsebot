"""Database enumerations."""
from __future__ import annotations

import enum


class Role(str, enum.Enum):
    """User role inside the system."""

    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"
    DESIGNER = "DESIGNER"

    @property
    def label(self) -> str:
        return _ROLE_LABELS[self]


class TaskStatus(str, enum.Enum):
    """Lifecycle status of a task."""

    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_REVIEW = "WAITING_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    DONE = "DONE"

    @property
    def is_active(self) -> bool:
        return self is not TaskStatus.DONE

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


class Priority(str, enum.Enum):
    """Task priority."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def label(self) -> str:
        return _PRIORITY_LABELS[self]


_ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Администратор",
    Role.CUSTOMER: "Заказчик",
    Role.DESIGNER: "Дизайнер",
}

# Status labels carry a status-specific emoji so that long lists are
# scannable at a glance.
_STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.NEW: "🆕 Новая",
    TaskStatus.IN_PROGRESS: "⚙️ В работе",
    TaskStatus.WAITING_REVIEW: "🔎 На проверке",
    TaskStatus.NEEDS_REVISION: "✏️ Нужны правки",
    TaskStatus.DONE: "✅ Выполнена",
}

# Coloured circles for priority — easy visual sort.
_PRIORITY_LABELS: dict[Priority, str] = {
    Priority.LOW: "🟢 Низкий",
    Priority.MEDIUM: "🟡 Средний",
    Priority.HIGH: "🔴 Высокий",
}
