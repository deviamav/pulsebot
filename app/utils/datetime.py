"""Date/time helpers for parsing and formatting user input."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Date formats accepted from users (ordered by preference)
_INPUT_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%Y-%m-%d",
)


def utcnow() -> datetime:
    """Return current time as timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def parse_deadline(text: str) -> datetime | None:
    """Parse a user-provided deadline string into a UTC datetime.

    Returns ``None`` if the input cannot be parsed.
    """
    text = text.strip()
    if not text:
        return None
    for fmt in _INPUT_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def format_dt(value: datetime | None, *, with_time: bool = True) -> str:
    """Format a datetime for display."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%d.%m.%Y %H:%M") if with_time else value.strftime("%d.%m.%Y")


def humanize_delta(target: datetime, *, now: datetime | None = None) -> str:
    """Return a coarse human-readable description of ``target - now``."""
    now = now or utcnow()
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = target - now
    overdue = delta.total_seconds() < 0
    delta = abs(delta)

    total_seconds = int(delta.total_seconds())
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes and not days:
        parts.append(f"{minutes}мин")
    if not parts:
        parts.append("только что")

    label = " ".join(parts)
    return f"просрочено на {label}" if overdue else f"через {label}"


def in_seconds(seconds: float) -> datetime:
    """Return a UTC datetime ``seconds`` into the future."""
    return utcnow() + timedelta(seconds=seconds)
