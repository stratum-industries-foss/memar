import logging
import os
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path


def log_dir() -> Path:
    """MEMAR_LOG_DIR if set, else <repo>/logs (source checkouts)."""
    env = os.getenv("MEMAR_LOG_DIR")
    return Path(env) if env else Path(__file__).parent.parent.parent / "logs"


def log_file() -> Path:
    return log_dir() / "backend.log"


def setup_logging():
    """Configure comprehensive logging for the backend.

    The rotating file is optional: if the log directory is not writable (for
    example a bind mount owned by another user), MEMAR logs to stdout only
    instead of refusing to start.
    """

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler - backend.log
    # INFO (not DEBUG): chatty third-party libs (aiosqlite logs every DB op,
    # websockets/httpcore every frame/request) flood backend.log at DEBUG and
    # fill the disk. Prod logs to file at INFO; raise to DEBUG temporarily for
    # debugging. App-specific DEBUG can still be added per-logger if needed.
    file_problem = None
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file(), maxBytes=20_000_000, backupCount=5)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
    except OSError as e:
        file_problem = e

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(console_handler)

    # Suppress noisy loggers. websockets.client + httpcore log every Moonraker
    # websocket frame and HTTP request at DEBUG — left uncapped they flood
    # backend.log at ~2.5 GB/day and fill the disk (observed 15 GB in production).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    # Get logger for app
    app_logger = logging.getLogger("memar")
    if file_problem is not None:
        app_logger.warning(
            "Cannot write log file in %s (%s); logging to the console only.", log_dir(), file_problem
        )
    return app_logger

# Initialize when imported
logger = setup_logging()
