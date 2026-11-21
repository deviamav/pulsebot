"""Aiogram routers."""
from aiogram import Router

from app.bot.handlers import admin, comments, common, customer, designer, errors, tasks


def get_main_router() -> Router:
    """Aggregate all routers in the right order.

    Order matters: role-specific routers must run before the generic
    ``common.fallback_router`` (which has a catch-all handler) so that
    reply-keyboard buttons reach their dedicated handlers first.
    """
    router = Router(name="main")
    router.include_routers(
        errors.router,
        common.router,
        customer.router,
        designer.router,
        admin.router,
        tasks.router,
        comments.router,
        common.fallback_router,
    )
    return router


__all__ = ["get_main_router"]
