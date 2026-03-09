"""Test that CELERY config in settings.py honors environment variables.

This validates the fix: when environment variables like CELERY_BROKER_URL are
set (e.g., via a .env file loaded by load_dotenv()), settings.py picks them up
instead of using the hardcoded defaults.
"""

import importlib
import importlib.util
import os
import sys


def _load_settings_module():
    """Load app/settings.py directly without triggering the full app package."""
    spec = importlib.util.spec_from_file_location(
        "_test_settings",
        os.path.join(os.path.dirname(__file__), "app", "settings.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_celery_settings_honor_env_vars(monkeypatch):
    """CELERY dict in settings.py should read broker_url from env."""
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://custom-host:6379/5")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://custom-host:6379/6")
    monkeypatch.setenv("CELERY_WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", "10")

    settings = _load_settings_module()

    assert settings.CELERY["broker_url"] == "redis://custom-host:6379/5"
    assert settings.CELERY["result_backend"] == "redis://custom-host:6379/6"
    assert settings.CELERY["worker_concurrency"] == 4
    assert settings.CELERY["worker_max_tasks_per_child"] == 10


def test_celery_settings_use_defaults_without_env(monkeypatch):
    """Without env vars, CELERY dict should use the hardcoded defaults."""
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
    monkeypatch.delenv("CELERY_WORKER_CONCURRENCY", raising=False)
    monkeypatch.delenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", raising=False)

    settings = _load_settings_module()

    assert settings.CELERY["broker_url"] == "redis://10.100.254.2/10"
    assert settings.CELERY["result_backend"] == "redis://10.100.254.2/10"
    assert settings.CELERY["worker_concurrency"] == 1
    assert settings.CELERY["worker_max_tasks_per_child"] == 1


def test_celery_settings_partial_override(monkeypatch):
    """Only the env vars that are set should override; others keep defaults."""
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://override-host:6379/0")
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
    monkeypatch.delenv("CELERY_WORKER_CONCURRENCY", raising=False)
    monkeypatch.delenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", raising=False)

    settings = _load_settings_module()

    assert settings.CELERY["broker_url"] == "redis://override-host:6379/0"
    assert settings.CELERY["result_backend"] == "redis://10.100.254.2/10"
    assert settings.CELERY["worker_concurrency"] == 1


def test_load_dotenv_runs_before_create_app():
    """Verify load_dotenv() is called before importing create_app in celery_app.py."""
    import ast

    with open("celery_app.py") as f:
        source = f.read()

    tree = ast.parse(source)
    statements = tree.body

    load_dotenv_line = None
    create_app_import_line = None

    for node in statements:
        # Find load_dotenv() call
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "load_dotenv":
                load_dotenv_line = node.lineno
        # Find 'from app import create_app'
        if isinstance(node, ast.ImportFrom) and node.module == "app":
            for alias in node.names:
                if alias.name == "create_app":
                    create_app_import_line = node.lineno

    assert load_dotenv_line is not None, "load_dotenv() call not found"
    assert create_app_import_line is not None, "from app import create_app not found"
    assert load_dotenv_line < create_app_import_line, (
        f"load_dotenv() (line {load_dotenv_line}) must come before "
        f"'from app import create_app' (line {create_app_import_line})"
    )
