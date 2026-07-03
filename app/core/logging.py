"""Central logging configuration.

Call `setup_logging()` once at application startup, then obtain loggers
anywhere with `get_logger(__name__)` so log records carry the module name.
"""

import logging
import sys

_APP_LOGGER_NAME = "code_review"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the application logger. Safe to call more than once."""
    logger = logging.getLogger(_APP_LOGGER_NAME)
    if logger.handlers:  # already configured (e.g. uvicorn --reload re-imports)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger namespaced under the application logger.

    `get_logger("app.services.repo_service")` → `code_review.app.services.repo_service`
    """
    if not name:
        return logging.getLogger(_APP_LOGGER_NAME)
    return logging.getLogger(f"{_APP_LOGGER_NAME}.{name}")
