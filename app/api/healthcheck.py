"""Lightweight aiohttp healthcheck server."""
from __future__ import annotations

from aiohttp import web
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import get_logger

logger = get_logger(__name__)


def build_health_app(*, engine: AsyncEngine, redis: Redis) -> web.Application:
    """Return an aiohttp application exposing ``/healthz`` and ``/readyz``."""
    app = web.Application()

    async def liveness(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def readiness(_: web.Request) -> web.Response:
        problems: list[str] = []
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            problems.append(f"postgres: {exc}")

        try:
            await redis.ping()
        except Exception as exc:
            problems.append(f"redis: {exc}")

        if problems:
            return web.json_response({"status": "fail", "errors": problems}, status=503)
        return web.json_response({"status": "ok"})

    app.router.add_get("/healthz", liveness)
    app.router.add_get("/readyz", readiness)
    return app


async def start_health_server(
    *, host: str, port: int, engine: AsyncEngine, redis: Redis
) -> web.AppRunner:
    """Start the healthcheck server and return its :class:`AppRunner`."""
    app = build_health_app(engine=engine, redis=redis)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("Health server started", host=host, port=port)
    return runner
