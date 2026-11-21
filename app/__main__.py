"""Entry point: ``python -m app``."""
from __future__ import annotations

import asyncio
import sys

from app.main import run


def main() -> None:
    """Bootstrap the application with uvloop where available."""
    if sys.platform != "win32":
        try:
            import uvloop  # type: ignore[import-not-found]

            uvloop.install()
        except ImportError:
            pass

    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
