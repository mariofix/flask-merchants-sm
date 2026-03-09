"""Application logging configuration.

Three named logging facilities are provided:

* ``sm.app``    - application events: logins, settings updates, missing keys,
                  password changes, application warnings.
* ``sm.celery`` - Celery task lifecycle: received, started, finished, retries,
                  and connection errors (logged at ERROR so Sentry picks them up).
* ``sm.audit``  - audit trail: payments, orders, pedidos, new users, abonos.
                  Replaces the legacy ``merchants_audit`` logger.
                  When a Celery Redis broker URL is available (``CELERY.broker_url``
                  or ``AUDIT_REDIS_URL``), records are stored in Redis using
                  :class:`RedisLogHandler` instead of a rotating file.  Each entry
                  is a self-contained JSON object that includes all HTTP request
                  headers (for API-key recovery) and the full request body, but
                  deliberately omits the client IP address.

Configuration
-------------
Place a ``LOGGING`` dict in ``app/settings.py`` (or any settings file loaded
via ``FLASK_APP_SETTINGS_FILE``).  The dict is passed verbatim to
:func:`logging.config.dictConfig`, giving full control over handlers,
formatters, and rotation.  When ``LOGGING`` is absent, sensible defaults are
applied: ``sm.app`` and ``sm.celery`` write rotating files; ``sm.audit`` uses
:class:`RedisLogHandler` when ``CELERY.broker_url`` (or ``AUDIT_REDIS_URL``)
points to a Redis instance, and falls back to a rotating file otherwise.

Redis audit-log tuning (scalar overrides, used only when ``LOGGING`` is absent):

* ``AUDIT_REDIS_URL``        - Redis URL; defaults to ``CELERY.broker_url``.
* ``AUDIT_REDIS_KEY``        - Redis list key; defaults to ``"sm:audit:log"``.
* ``AUDIT_REDIS_MAX_ENTRIES``- Maximum list length (LTRIM); defaults to ``1000``.

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

import json
import logging
import logging.config
import os
from datetime import datetime, timezone
from typing import Any

# HTTP header names (lowercase) that reveal the client IP address.  These are
# excluded from logged request headers so that audit records contain no IP data.
# Comparison is performed against lowercased header names for robustness.
_IP_HEADERS_LOWER: frozenset[str] = frozenset(
    {
        "x-forwarded-for",
        "x-real-ip",
        "cf-connecting-ip",
        "true-client-ip",
        "x-client-ip",
        "forwarded",
    }
)


class RedisLogHandler(logging.Handler):
    """Logging handler that stores JSON-serialised log records in a Redis list.

    Used for the ``sm.audit`` logger so that payment-webhook events are
    reliably persisted in the same Redis instance used by Celery, and are
    immediately visible via the admin Redis CLI view.

    Each stored entry is a JSON object containing:

    * ``timestamp`` – ISO-8601 UTC timestamp
    * ``level``     – log level name
    * ``logger``    – logger name
    * ``message``   – formatted log message
    * ``headers``   – all HTTP request headers when a request context is
                      active (IP-related headers are excluded), useful for
                      recovering provider API keys sent by payment webhooks
    * ``method``    – HTTP method
    * ``url``       – full request URL (path + query string)
    * ``args``      – URL query parameters
    * ``form``      – form-encoded body fields
    * ``data``      – raw request body (text)
    * ``json``      – parsed JSON body (when ``Content-Type: application/json``)

    The client IP address (``remote_addr``) and all IP-forwarding headers are
    deliberately omitted.

    Parameters
    ----------
    redis_url:
        Redis connection URL (e.g. ``redis://host/db``).
    key:
        Redis list key under which log entries are prepended.
        Defaults to ``"sm:audit:log"``.
    max_entries:
        Maximum number of entries kept in the list (``LTRIM`` after each
        ``LPUSH``).  ``0`` means unlimited.  Defaults to ``1000``.
    """

    def __init__(
        self,
        redis_url: str,
        key: str = "sm:audit:log",
        max_entries: int = 1000,
    ) -> None:
        super().__init__()
        self._redis_url = redis_url
        self._key = key
        self._max_entries = max_entries
        self._client: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Lazily create and return the Redis client."""
        if self._client is None:
            import redis  # noqa: PLC0415

            self._client = redis.from_url(self._redis_url, socket_connect_timeout=2)
        return self._client

    def _build_entry(self, record: logging.LogRecord) -> dict:
        """Build the dict that will be JSON-serialised and stored in Redis."""
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }

        try:
            from flask import has_request_context  # noqa: PLC0415
            from flask import request as flask_request  # noqa: PLC0415

            if has_request_context():
                # All headers except those that carry IP information.
                # Retaining all other headers (e.g. Authorization, X-Api-Key,
                # Content-Type) is essential to recover provider API keys.
                entry["headers"] = {
                    k: v
                    for k, v in flask_request.headers.items()
                    if k.lower() not in _IP_HEADERS_LOWER
                }
                entry["method"] = flask_request.method
                entry["url"] = flask_request.url
                entry["args"] = dict(flask_request.args)
                entry["form"] = dict(flask_request.form)

                raw_data = flask_request.get_data(as_text=True)
                if raw_data:
                    entry["data"] = raw_data
                    try:
                        json_body = flask_request.get_json(silent=True, force=True)
                        if json_body is not None:
                            entry["json"] = json_body
                    except Exception:  # noqa: BLE001
                        pass

                # remote_addr and IP-forwarding headers are intentionally not
                # included per requirements.
        except ImportError:
            pass

        return entry

    def emit(self, record: logging.LogRecord) -> None:
        """Serialise *record* and push it to the Redis list."""
        try:
            entry = self._build_entry(record)
            client = self._get_client()
            client.lpush(self._key, json.dumps(entry, default=str))
            if self._max_entries > 0:
                client.ltrim(self._key, 0, self._max_entries - 1)
        except Exception:  # noqa: BLE001
            self.handleError(record)


def configure_logging(app) -> None:
    """Configure the three logging facilities from *app.config['LOGGING']*.

    When ``LOGGING`` is set in the Flask config the dict is passed directly to
    :func:`logging.config.dictConfig`, giving the operator full control.
    Otherwise, sensible defaults are applied: ``sm.app`` and ``sm.celery``
    use rotating files; ``sm.audit`` uses :class:`RedisLogHandler` when a
    Redis URL is available (``AUDIT_REDIS_URL`` or ``CELERY.broker_url``),
    and falls back to a rotating file otherwise.

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
    """Set up the three loggers.

    ``sm.app`` and ``sm.celery`` use rotating files under ``logs/``.
    ``sm.audit`` uses :class:`RedisLogHandler` when a Redis URL is configured
    (``AUDIT_REDIS_URL`` or ``CELERY.broker_url``); otherwise it falls back to
    a rotating file so the test suite (which uses an in-memory broker) is
    unaffected.
    """
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

    # sm.audit: use Redis when a broker URL is available so that webhook events
    # are stored in one accessible place alongside Celery task data, and are
    # not lost to rotating-file issues.
    celery_cfg = cfg.get("CELERY", {})
    redis_url = cfg.get("AUDIT_REDIS_URL") or celery_cfg.get("broker_url", "")
    if redis_url and redis_url.startswith("redis"):
        _setup_redis_logger(
            name="sm.audit",
            redis_url=redis_url,
            key=cfg.get("AUDIT_REDIS_KEY", "sm:audit:log"),
            max_entries=cfg.get("AUDIT_REDIS_MAX_ENTRIES", 1000),
            level=cfg.get("AUDIT_LOG_LEVEL", "INFO"),
            formatter=formatter,
        )
    else:
        # Fallback to file when no Redis URL is configured (e.g. in tests).
        _setup_logger(
            name="sm.audit",
            filename=cfg.get("AUDIT_LOG_FILE", os.path.join(log_dir, "audit.log")),
            level=cfg.get("AUDIT_LOG_LEVEL", "INFO"),
            backup_count=cfg.get("AUDIT_LOG_BACKUP_COUNT", 30),
            formatter=formatter,
        )


def _setup_redis_logger(
    name: str,
    redis_url: str,
    key: str,
    max_entries: int,
    level: str,
    formatter: logging.Formatter,
) -> logging.Logger:
    """Configure *name* with a :class:`RedisLogHandler` if not already set up."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = RedisLogHandler(redis_url, key=key, max_entries=max_entries)
    handler.setFormatter(formatter)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


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
