"""Application bootstrap and shutdown orchestration."""
from __future__ import annotations

import asyncio
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram.types import BotCommand
from redis.asyncio import Redis

from app.api.healthcheck import start_health_server
from app.bot.handlers import get_main_router
from app.bot.middlewares import (
    AuthMiddleware,
    DbSessionMiddleware,
    MediaGroupMiddleware,
    StructlogContextMiddleware,
    TaskFocusGuardMiddleware,
    ThrottlingMiddleware,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import build_engine, build_sessionmaker
from app.services import NotificationService, ReminderScheduler

logger = get_logger(__name__)


async def run() -> None:
    """Main entry: wire dependencies, start the bot and serve until shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level, env=settings.env)
    logger.info(
        "Starting application",
        env=settings.env,
        log_level=settings.log_level,
    )

    # --- Infrastructure ---------------------------------------------------
    engine = build_engine(settings.postgres)
    sessionmaker = build_sessionmaker(engine)

    redis: Redis = Redis.from_url(
        settings.redis.url, encoding="utf-8", decode_responses=False
    )

    storage = RedisStorage(
        redis=redis,
        key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
    )

    # --- Bot --------------------------------------------------------------
    bot = Bot(
        token=settings.bot.token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    notifications = NotificationService(bot)

    # Workflow data - available to all handlers
    dp["notifications"] = notifications

    # --- Middlewares ------------------------------------------------------
    dp.update.outer_middleware(StructlogContextMiddleware())
    dp.update.outer_middleware(
        DbSessionMiddleware(
            sessionmaker=sessionmaker, admin_ids=settings.bot.admin_ids
        )
    )
    dp.update.outer_middleware(AuthMiddleware())
    dp.update.middleware(
        ThrottlingMiddleware(
            redis=redis, rate_per_second=settings.rate_limit_per_second
        )
    )
    # Drops TaskFocus when user navigates via menu / slash commands.
    dp.message.middleware(TaskFocusGuardMiddleware())
    # Coalesce media-group (album) messages into one handler invocation.
    dp.message.middleware(MediaGroupMiddleware())

    dp.include_router(get_main_router())

    # --- Default bot commands (shown in Telegram "/" suggestions) --------
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Запуск / главное меню"),
                BotCommand(command="help", description="Справка"),
                BotCommand(command="cancel", description="Отменить текущее действие"),
                BotCommand(command="newtask", description="Создать задачу"),
            ]
        )
    except Exception as exc:
        logger.warning("Failed to set bot commands", error=str(exc))

    # --- Background services ---------------------------------------------
    scheduler = ReminderScheduler(
        sessionmaker=sessionmaker,
        notifications=notifications,
        interval_seconds=settings.reminder_check_interval_seconds,
    )

    # --- Healthcheck HTTP -------------------------------------------------
    health_runner = await start_health_server(
        host=settings.healthcheck_host,
        port=settings.healthcheck_port,
        engine=engine,
        redis=redis,
    )

    # --- Graceful shutdown handling --------------------------------------
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows / non-unix platforms
            pass

    await scheduler.start()

    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        name="aiogram-polling",
    )

    stop_task = asyncio.create_task(stop_event.wait(), name="stop-event")

    done, _pending = await asyncio.wait(
        [polling_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    logger.info("Shutting down")

    # --- Tear down --------------------------------------------------------
    if polling_task in done and polling_task.exception() is not None:
        logger.exception("Polling task crashed", error=polling_task.exception())

    await dp.stop_polling()
    if not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except (asyncio.CancelledError, Exception):
            pass

    await scheduler.stop()

    try:
        await bot.session.close()
    except Exception as exc:
        logger.warning("Bot session close failed", error=str(exc))

    try:
        await health_runner.cleanup()
    except Exception as exc:
        logger.warning("Health server cleanup failed", error=str(exc))

    try:
        await redis.aclose()
    except Exception as exc:
        logger.warning("Redis close failed", error=str(exc))

    try:
        await engine.dispose()
    except Exception as exc:
        logger.warning("Engine dispose failed", error=str(exc))

    logger.info("Bye")
