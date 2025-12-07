import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import LOG_DIR


def setupLogging() -> None:
    """
    Basic logging setup for Control Pod.

    - Logs to LOG_DIR/controlpod_service.log (rotating file)
    - Logs to console (stdout)
    - INFO level by default
    """
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "controlpod_service.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()

    # Clear any existing handlers so we don't duplicate logs
    if root.handlers:
        root.handlers.clear()

    root.setLevel(logging.INFO)

    # File handler (rotating)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,   # ~1 MB per file
        backupCount=3,        # keep a few old logs
    )
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

