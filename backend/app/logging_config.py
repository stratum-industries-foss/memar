import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

def setup_logging():
    """Configure comprehensive logging for the backend."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

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
    file_handler = RotatingFileHandler(
        log_dir / "backend.log", maxBytes=100_000_000, backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)

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
    return app_logger

# Initialize when imported
logger = setup_logging()
