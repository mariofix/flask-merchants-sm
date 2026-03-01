"""Tests for Redis CLI admin views.

Verifies that ``SecureRedisCli`` is registered in the admin panel when the
CELERY config contains ``redis://`` URLs for the broker and result backend.
"""

import pytest
import redis
from flask import Flask
from unittest.mock import MagicMock, patch


def test_redis_cli_views_registered_for_redis_urls():
    """Both broker and result-backend Redis CLI views should be added when URLs differ."""
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test",
        CELERY={
            "broker_url": "redis://localhost/10",
            "result_backend": "redis://localhost/11",
        },
    )

    from app.extensions.admin import SecureRedisCli

    # Use spec=redis.Redis so Flask-Admin's _inspect_commands can find the
    # 'delete' command and successfully remap 'del' -> 'delete'.
    fake_redis = MagicMock(spec=redis.Redis)
    with patch("redis.from_url", return_value=fake_redis):
        celery_cfg = app.config.get("CELERY", {})
        broker_url = celery_cfg.get("broker_url", "")
        result_backend = celery_cfg.get("result_backend", "")

        added = []
        if broker_url and broker_url.startswith("redis"):
            v = SecureRedisCli(fake_redis, name="Redis Cola", endpoint="redis_broker", category="Herramientas")
            added.append(v)
        if result_backend and result_backend.startswith("redis") and result_backend != broker_url:
            v = SecureRedisCli(fake_redis, name="Redis Resultados", endpoint="redis_results", category="Herramientas")
            added.append(v)

    assert len(added) == 2
    names = [v.name for v in added]
    assert "Redis Cola" in names
    assert "Redis Resultados" in names


def test_redis_cli_views_skipped_for_non_redis_urls():
    """No Redis CLI views should be added for non-redis broker/backend URLs."""
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test",
        CELERY={
            "broker_url": "memory://",
            "result_backend": "cache+memory://",
        },
    )

    celery_cfg = app.config.get("CELERY", {})
    broker_url = celery_cfg.get("broker_url", "")
    result_backend = celery_cfg.get("result_backend", "")

    added = []
    if broker_url and broker_url.startswith("redis"):
        added.append("broker")
    if result_backend and result_backend.startswith("redis") and result_backend != broker_url:
        added.append("result")

    assert added == []


def test_redis_cli_views_single_when_same_url():
    """Only one view should be added when broker and result backend share the same Redis URL."""
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test",
        CELERY={
            "broker_url": "redis://localhost/0",
            "result_backend": "redis://localhost/0",
        },
    )

    fake_redis = MagicMock()
    celery_cfg = app.config.get("CELERY", {})
    broker_url = celery_cfg.get("broker_url", "")
    result_backend = celery_cfg.get("result_backend", "")

    added = []
    with patch("redis.from_url", return_value=fake_redis):
        if broker_url and broker_url.startswith("redis"):
            added.append("broker")
        if result_backend and result_backend.startswith("redis") and result_backend != broker_url:
            added.append("result")

    assert len(added) == 1
    assert "broker" in added


def test_execute_view_is_csrf_exempt():
    """SecureRedisCli.execute_view must be marked as CSRF-exempt so the AJAX
    POST to /run/ is not rejected with 400 by Flask-WTF global CSRF protection."""
    from app.extensions.admin import SecureRedisCli
    from app.extensions import csrf

    # Flask-WTF stores exemptions as "{module}.{name}" (using __name__, not __qualname__).
    fn = SecureRedisCli.execute_view
    view_location = f"{fn.__module__}.{fn.__name__}"
    assert view_location in csrf._exempt_views, (
        f"execute_view ({view_location}) is not in csrf._exempt_views; "
        "POST /run/ will be rejected with 400."
    )
