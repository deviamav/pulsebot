"""Global error handler hiding internals from end-users."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import ErrorEvent

from app.core.logging import get_logger

router = Router(name="errors")
logger = get_logger(__name__)


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    """Log all unhandled exceptions, and politely notify the user."""
    update = event.update
    exception = event.exception

    logger.exception(
        "Unhandled exception in handler",
        update_id=getattr(update, "update_id", None),
        error=str(exception),
        exc_info=exception,
    )

    try:
        if update is not None and update.message is not None:
            await update.message.answer(
                "Произошла внутренняя ошибка. Попробуйте ещё раз чуть позже."
            )
        elif update is not None and update.callback_query is not None:
            await update.callback_query.answer(
                "Произошла внутренняя ошибка. Попробуйте ещё раз.",
                show_alert=True,
            )
    except Exception as notify_exc:
        logger.warning("Failed to notify user about error", error=str(notify_exc))

    return True
