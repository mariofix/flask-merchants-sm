"""Tests for app.logging_config.configure_logging."""

import logging
import os
import tempfile

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
