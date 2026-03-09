"""Application logging configuration.

Three named logging facilities are provided:

* ``sm.app``    - application events: logins, settings updates, missing keys,
                  password changes, application warnings.
* ``sm.celery`` - Celery task lifecycle: received, started, finished, retries,
                  and connection errors (logged at ERROR so Sentry picks them up).
* ``sm.audit``  - audit trail: payments, orders, pedidos, new users, abonos.
                  Replaces the legacy ``merchants_audit`` logger.

Configuration
-------------
Place a ``LOGGING`` dict in ``app/settings.py`` (or any settings file loaded
via ``FLASK_APP_SETTINGS_FILE``).  The dict is passed verbatim to
:func:`logging.config.dictConfig`, giving full control over handlers,
formatters, and rotation.  When ``LOGGING`` is absent, sensible defaults
writing rotating files to the ``logs/`` directory are used.

Example ``settings.py`` entry::

    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "app_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": "logs/app.log",
                "when": "midnight",
                "backupCount": 14,
                "encoding": "utf-8",
                "formatter": "standard",
            },
            "celery_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": "logs/celery.log",
                "when": "midnight",
                "backupCount": 14,
                "encoding": "utf-8",
                "formatter": "standard",
            },
            "audit_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": "logs/audit.log",
                "when": "midnight",
                "backupCount": 30,
                "encoding": "utf-8",
                "formatter": "standard",
            },
        },
        "loggers": {
            "sm.app": {
                "handlers": ["app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "sm.celery": {
                "handlers": ["celery_file"],
                "level": "INFO",
                "propagate": False,
            },
            "sm.audit": {
                "handlers": ["audit_file"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
"""

from __future__ import annotations

import logging
import logging.config
import os


def configure_logging(app) -> None:
    """Configure the three logging facilities from *app.config['LOGGING']*.

    When ``LOGGING`` is set in the Flask config the dict is passed directly to
    :func:`logging.config.dictConfig`, giving the operator full control.
    Otherwise, sensible rotating-file defaults are applied.

    The ``logs/`` directory is created automatically if it does not exist.
    """
    logging_config = app.config.get("LOGGING")
    if logging_config:
        _ensure_log_dirs(logging_config)
        logging.config.dictConfig(logging_config)
    else:
        _apply_defaults(app)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _apply_defaults(app) -> None:
    """Set up the three loggers with rotating file handlers under ``logs/``."""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    cfg = app.config
    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    _setup_logger(
        name="sm.app",
        filename=cfg.get("APP_LOG_FILE", os.path.join(log_dir, "app.log")),
        level=cfg.get("APP_LOG_LEVEL", "INFO"),
        backup_count=cfg.get("APP_LOG_BACKUP_COUNT", 14),
        formatter=formatter,
    )
    _setup_logger(
        name="sm.celery",
        filename=cfg.get("CELERY_LOG_FILE", os.path.join(log_dir, "celery.log")),
        level=cfg.get("CELERY_LOG_LEVEL", "INFO"),
        backup_count=cfg.get("CELERY_LOG_BACKUP_COUNT", 14),
        formatter=formatter,
    )
    _setup_logger(
        name="sm.audit",
        filename=cfg.get("AUDIT_LOG_FILE", os.path.join(log_dir, "audit.log")),
        level=cfg.get("AUDIT_LOG_LEVEL", "INFO"),
        backup_count=cfg.get("AUDIT_LOG_BACKUP_COUNT", 30),
        formatter=formatter,
    )


def _setup_logger(
    name: str,
    filename: str,
    level: str,
    backup_count: int,
    formatter: logging.Formatter,
) -> logging.Logger:
    """Configure *name* with a single ``TimedRotatingFileHandler`` if not already set up."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)

    from logging.handlers import TimedRotatingFileHandler

    handler = TimedRotatingFileHandler(
        filename,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _ensure_log_dirs(config: dict) -> None:
    """Create parent directories for every file-based handler in *config*."""
    for handler_cfg in config.get("handlers", {}).values():
        filename = handler_cfg.get("filename")
        if filename:
            parent = os.path.dirname(filename)
            if parent:
                os.makedirs(parent, exist_ok=True)
            else:
                os.makedirs("logs", exist_ok=True)
