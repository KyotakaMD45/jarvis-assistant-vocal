"""File logging to jarvis.log (rotating, so it never grows without limit)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from jarvis.paths import LOG_PATH

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once. Never raises."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    try:
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        # Log file not writable (read-only folder, file locked...): keep running without it.
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)
    # Keep third-party libraries quiet unless something goes wrong.
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "comtypes", "aiohttp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
