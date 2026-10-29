"""File logging seam — keep ``logs/*.log`` readable on every platform.

On Windows the start scripts launch the app through ``.venv\\Scripts\\
python.exe`` — a uv launcher that re-execs the real interpreter from the
uv-managed Python install. The re-exec drops the stdout/stderr handles
``Start-Process -RedirectStandard*`` passed in, so ``logs/api.log`` and
``logs/ui.log`` stay empty (0 bytes) even while the server answers
requests: there is nowhere to read the traceback of a failed turn.

The app therefore writes its own rotating file log, anchored at the
repository's ``logs/`` directory (not the process cwd):

* :func:`install_file_logger` — attach a rotating UTF-8 handler to the
  root logger (idempotent; never raises — logging must not take the app
  down);
* :func:`route_uvicorn_logs_to_root` — make ``uvicorn*`` loggers
  propagate to the root. Must run from the FastAPI lifespan: uvicorn
  applies its own ``dictConfig`` *after* importing the app, so handlers
  added at import time would be replaced;
* :func:`configure_cli_logging` — configure the root logger for the
  ``orya`` CLI entry points (MVP-POLISH-3) so their ``logger.info``
  summaries are actually emitted.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

#: Repository ``logs/`` directory (package location, not the process cwd).
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
#: Rotate at ~5 MB, keep three backups — same budget as the script logs.
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

#: Loggers owned by uvicorn's own dictConfig.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def install_file_logger(name: str, level: int = logging.INFO) -> Path | None:
    """Attach a rotating file handler writing ``logs/{name}``.

    Returns the log file path, or ``None`` when the directory or file
    cannot be created. Repeated calls with the same ``name`` do not add
    duplicate handlers.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / name
        handler = RotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        logging.getLogger(__name__).warning("file logging unavailable: %s", LOG_DIR)
        return None

    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.setLevel(level)

    root = logging.getLogger()
    target = str(path)
    for existing in root.handlers:
        if getattr(existing, "baseFilename", None) == target:
            return path  # already installed (idempotent)
    root.addHandler(handler)
    return path


def configure_cli_logging() -> None:
    """Configure root logging for the ``orya`` CLI entry points (MVP-POLISH-3).

    Both ``orya ...`` (``app.main:main``) and ``python -m app.db.migrate``
    report their results through the ``logging`` module now — ``print()``
    is reserved for interactive prompts. ``logging.basicConfig`` alone is
    not enough: it is a no-op when the root logger already has handlers
    (e.g. ``app.main`` was imported first), and ``python -m app.db.migrate``
    never imports it at all — without configuration ``logger.info`` output
    would be dropped (the module's fallback handler emits WARNING+ only).
    The level follows ``settings.log_level`` like the file logger does.
    """
    from app.core.config import get_settings

    name = str(get_settings().log_level or "INFO").upper()
    level = getattr(logging, name, logging.INFO)
    logging.basicConfig(level=level, format=_FORMAT)
    logging.getLogger().setLevel(level)


def route_uvicorn_logs_to_root() -> None:
    """Let the ``uvicorn*`` loggers propagate to the root logger.

    Uvicorn gives them their own handlers with ``propagate=False``; after
    this call their records (including the ASGI tracebacks of a 500)
    reach the root handlers — stderr *and* the file logger.
    """
    for name in _UVICORN_LOGGERS:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True
