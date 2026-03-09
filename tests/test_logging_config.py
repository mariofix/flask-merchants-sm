"""Tests for app.logging_config.configure_logging."""

import json
import logging
import os
import tempfile
from logging.handlers import TimedRotatingFileHandler
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture()
def minimal_app(tmp_path):
    """Minimal Flask app whose config points log files at *tmp_path*."""
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        APP_LOG_FILE=str(tmp_path / "app.log"),
        CELERY_LOG_FILE=str(tmp_path / "celery.log"),
        AUDIT_LOG_FILE=str(tmp_path / "audit.log"),
    )
    return app


def _reset_logger(name: str) -> None:
    """Remove all handlers from *name* so configure_logging can re-apply them."""
    logger = logging.getLogger(name)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()


@pytest.fixture(autouse=True)
def reset_loggers():
    """Ensure each test starts with clean logger state."""
    for name in ("sm.app", "sm.celery", "sm.audit"):
        _reset_logger(name)
    yield
    for name in ("sm.app", "sm.celery", "sm.audit"):
        _reset_logger(name)


class TestConfigureLoggingDefaults:
    def test_three_loggers_created(self, minimal_app, tmp_path):
        from app.logging_config import configure_logging

        with minimal_app.app_context():
            configure_logging(minimal_app)

        for name in ("sm.app", "sm.celery", "sm.audit"):
            logger = logging.getLogger(name)
            assert logger.handlers, f"{name} should have at least one handler"

    def test_log_files_written(self, minimal_app, tmp_path):
        from app.logging_config import configure_logging

        with minimal_app.app_context():
            configure_logging(minimal_app)

        logging.getLogger("sm.app").info("app_test_message")
        logging.getLogger("sm.celery").info("celery_test_message")
        logging.getLogger("sm.audit").info("audit_test_message")

        # Flush all handlers
        for name in ("sm.app", "sm.celery", "sm.audit"):
            for h in logging.getLogger(name).handlers:
                h.flush()

        app_log = tmp_path / "app.log"
        celery_log = tmp_path / "celery.log"
        audit_log = tmp_path / "audit.log"

        assert app_log.exists(), "logs/app.log should be created"
        assert celery_log.exists(), "logs/celery.log should be created"
        assert audit_log.exists(), "logs/audit.log should be created"

        assert "app_test_message" in app_log.read_text()
        assert "celery_test_message" in celery_log.read_text()
        assert "audit_test_message" in audit_log.read_text()

    def test_loggers_do_not_propagate(self, minimal_app):
        from app.logging_config import configure_logging

        with minimal_app.app_context():
            configure_logging(minimal_app)

        for name in ("sm.app", "sm.celery", "sm.audit"):
            assert not logging.getLogger(name).propagate, f"{name} should not propagate"

    def test_audit_logger_alias(self, minimal_app):
        """merchants_audit must point at sm.audit."""
        from flask_merchants import merchants_audit

        assert merchants_audit.name == "sm.audit"


class TestConfigureLoggingDictConfig:
    def test_full_dictconfig_respected(self, tmp_path):
        from app.logging_config import configure_logging

        custom_app_log = str(tmp_path / "custom_app.log")
        app = Flask(__name__)
        app.config["LOGGING"] = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "simple": {"format": "%(message)s"},
            },
            "handlers": {
                "app_file": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "filename": custom_app_log,
                    "when": "midnight",
                    "backupCount": 7,
                    "encoding": "utf-8",
                    "formatter": "simple",
                },
            },
            "loggers": {
                "sm.app": {"handlers": ["app_file"], "level": "DEBUG", "propagate": False},
                "sm.celery": {"handlers": [], "level": "WARNING", "propagate": False},
                "sm.audit": {"handlers": [], "level": "WARNING", "propagate": False},
            },
        }

        with app.app_context():
            configure_logging(app)

        logger = logging.getLogger("sm.app")
        logger.debug("dictconfig_message")
        for h in logger.handlers:
            h.flush()

        with open(custom_app_log) as f:
            content = f.read()
        assert "dictconfig_message" in content


class TestRedisLogHandler:
    """Tests for RedisLogHandler."""

    def test_emit_pushes_json_to_redis(self):
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10", key="test:log", max_entries=100)
        mock_client = MagicMock()
        handler._client = mock_client

        record = logging.LogRecord(
            name="sm.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="payment approved code=%s",
            args=("ABC123",),
            exc_info=None,
        )
        handler.emit(record)

        mock_client.lpush.assert_called_once()
        key, raw = mock_client.lpush.call_args[0]
        assert key == "test:log"
        entry = json.loads(raw)
        assert entry["level"] == "INFO"
        assert entry["logger"] == "sm.audit"
        assert "ABC123" in entry["message"]
        assert "timestamp" in entry

    def test_emit_trims_list_to_max_entries(self):
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10", key="test:log", max_entries=50)
        mock_client = MagicMock()
        handler._client = mock_client

        record = logging.LogRecord(
            name="sm.audit", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        handler.emit(record)
        mock_client.ltrim.assert_called_once_with("test:log", 0, 49)

    def test_emit_no_trim_when_max_entries_zero(self):
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10", key="test:log", max_entries=0)
        mock_client = MagicMock()
        handler._client = mock_client

        record = logging.LogRecord(
            name="sm.audit", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        handler.emit(record)
        mock_client.ltrim.assert_not_called()

    def test_emit_handles_redis_error_gracefully(self):
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10")
        mock_client = MagicMock()
        mock_client.lpush.side_effect = Exception("connection refused")
        handler._client = mock_client

        record = logging.LogRecord(
            name="sm.audit", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        # Should not raise; handleError is called instead
        with patch.object(handler, "handleError") as mock_he:
            handler.emit(record)
            mock_he.assert_called_once_with(record)

    def test_build_entry_includes_request_headers_without_ip(self):
        """Headers present in request context are captured; IP headers are excluded."""
        from app.logging_config import RedisLogHandler, _IP_HEADERS_LOWER

        handler = RedisLogHandler("redis://localhost/10")
        app = Flask(__name__)
        with app.test_request_context(
            "/merchants/webhook/khipu",
            method="POST",
            headers={
                "Authorization": "Bearer secret-token",
                "X-Api-Key": "khipu-key-123",
                "Content-Type": "application/json",
                "X-Forwarded-For": "203.0.113.5",
                "X-Real-IP": "203.0.113.5",
            },
            data=json.dumps({"payment_id": "pay_abc", "amount": 5000}),
            content_type="application/json",
        ):
            record = logging.LogRecord(
                name="sm.audit", level=logging.INFO, pathname="", lineno=0,
                msg="webhook", args=(), exc_info=None,
            )
            entry = handler._build_entry(record)

        assert "headers" in entry
        # Non-IP headers are retained
        assert entry["headers"].get("Authorization") == "Bearer secret-token"
        assert entry["headers"].get("X-Api-Key") == "khipu-key-123"
        # IP headers are excluded (case-insensitive)
        for header_name, header_value in entry["headers"].items():
            assert header_name.lower() not in _IP_HEADERS_LOWER, (
                f"IP header {header_name!r} should have been excluded"
            )

    def test_build_entry_excludes_remote_addr(self):
        """remote_addr must not appear anywhere in the logged entry."""
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10")
        app = Flask(__name__)
        with app.test_request_context(
            "/webhook",
            method="POST",
            environ_base={"REMOTE_ADDR": "10.0.0.1"},
        ):
            record = logging.LogRecord(
                name="sm.audit", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            entry = handler._build_entry(record)

        serialised = json.dumps(entry)
        assert "10.0.0.1" not in serialised

    def test_build_entry_includes_method_url_args_form(self):
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10")
        app = Flask(__name__)
        with app.test_request_context(
            "/webhook?ref=test",
            method="POST",
            data={"field": "value"},
        ):
            record = logging.LogRecord(
                name="sm.audit", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            entry = handler._build_entry(record)

        assert entry["method"] == "POST"
        assert "ref=test" in entry["url"] or entry["args"].get("ref") == "test"
        assert entry["form"].get("field") == "value"

    def test_build_entry_includes_json_body(self):
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10")
        app = Flask(__name__)
        payload = {"payment_id": "khipu_xyz", "status": "done"}
        with app.test_request_context(
            "/webhook",
            method="POST",
            data=json.dumps(payload),
            content_type="application/json",
        ):
            record = logging.LogRecord(
                name="sm.audit", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            entry = handler._build_entry(record)

        assert entry.get("json") == payload
        assert "payment_id" in entry.get("data", "")

    def test_build_entry_without_request_context(self):
        """Outside a request context only core fields are present."""
        from app.logging_config import RedisLogHandler

        handler = RedisLogHandler("redis://localhost/10")
        record = logging.LogRecord(
            name="sm.audit", level=logging.INFO, pathname="", lineno=0,
            msg="no request context", args=(), exc_info=None,
        )
        entry = handler._build_entry(record)

        assert entry["level"] == "INFO"
        assert "no request context" in entry["message"]
        assert "headers" not in entry
        assert "method" not in entry


class TestAuditLoggerUsesRedis:
    """Integration tests: configure_logging routes sm.audit to the right handler."""

    def test_audit_uses_redis_handler_when_celery_broker_is_redis(self, tmp_path):
        from app.logging_config import configure_logging, RedisLogHandler

        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            CELERY={"broker_url": "redis://localhost/10"},
            APP_LOG_FILE=str(tmp_path / "app.log"),
            CELERY_LOG_FILE=str(tmp_path / "celery.log"),
        )

        with app.app_context():
            configure_logging(app)

        audit_logger = logging.getLogger("sm.audit")
        assert any(isinstance(h, RedisLogHandler) for h in audit_logger.handlers), (
            "sm.audit should use RedisLogHandler when CELERY.broker_url is redis://"
        )

    def test_audit_uses_redis_when_audit_redis_url_set(self, tmp_path):
        from app.logging_config import configure_logging, RedisLogHandler

        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            AUDIT_REDIS_URL="redis://dedicated-redis/5",
            APP_LOG_FILE=str(tmp_path / "app.log"),
            CELERY_LOG_FILE=str(tmp_path / "celery.log"),
        )

        with app.app_context():
            configure_logging(app)

        audit_logger = logging.getLogger("sm.audit")
        assert any(isinstance(h, RedisLogHandler) for h in audit_logger.handlers), (
            "sm.audit should use RedisLogHandler when AUDIT_REDIS_URL is set"
        )

    def test_audit_falls_back_to_file_without_redis(self, minimal_app):
        from app.logging_config import configure_logging

        with minimal_app.app_context():
            configure_logging(minimal_app)

        audit_logger = logging.getLogger("sm.audit")
        assert any(isinstance(h, TimedRotatingFileHandler) for h in audit_logger.handlers), (
            "sm.audit should fall back to TimedRotatingFileHandler when no Redis URL"
        )

    def test_redis_handler_key_and_max_entries_from_config(self, tmp_path):
        from app.logging_config import configure_logging, RedisLogHandler

        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            CELERY={"broker_url": "redis://localhost/10"},
            AUDIT_REDIS_KEY="custom:audit",
            AUDIT_REDIS_MAX_ENTRIES=250,
            APP_LOG_FILE=str(tmp_path / "app.log"),
            CELERY_LOG_FILE=str(tmp_path / "celery.log"),
        )

        with app.app_context():
            configure_logging(app)

        audit_logger = logging.getLogger("sm.audit")
        redis_handlers = [h for h in audit_logger.handlers if isinstance(h, RedisLogHandler)]
        assert redis_handlers, "Expected at least one RedisLogHandler"
        handler = redis_handlers[0]
        assert handler._key == "custom:audit"
        assert handler._max_entries == 250
