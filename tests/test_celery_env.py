"""Test that Daleks mailer configuration in settings.py is correct.

Validates that DALEKS_URL and DALEKS_FROM_EMAIL are present with expected
defaults, and that the DaleksMailUtil integration is properly wired.
"""

import ast
import importlib
import importlib.util
import os


def _load_settings_module():
    """Load app/settings.py directly without triggering the full app package."""
    project_root = os.path.dirname(os.path.dirname(__file__))
    spec = importlib.util.spec_from_file_location(
        "_test_settings",
        os.path.join(project_root, "app", "settings.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_daleks_url_default():
    """DALEKS_URL should default to the local daleks service."""
    settings = _load_settings_module()
    assert settings.DALEKS_URL == "http://zvn-lin2.local:2525"


def test_daleks_from_email_default():
    """DALEKS_FROM_EMAIL should have a sensible default sender address."""
    settings = _load_settings_module()
    assert "@" in settings.DALEKS_FROM_EMAIL


def test_daleks_mail_util_is_importable():
    """DaleksMailUtil should be importable from daleks.contrib."""
    from daleks.contrib.flask_security_mail import DaleksMailUtil
    from flask_security.mail_util import MailUtil

    assert issubclass(DaleksMailUtil, MailUtil)


def test_daleks_client_is_importable():
    """DaleksClient should be importable from daleks.contrib.client."""
    from daleks.contrib.client import DaleksClient

    client = DaleksClient("http://localhost:2525")
    assert client.base_url == "http://localhost:2525"
    assert client.timeout == 10


def test_send_daleks_email_helper_exists():
    """_send_daleks_email helper should be importable from app.tasks."""
    import ast

    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "tasks.py")) as f:
        tree = ast.parse(f.read())

    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "_send_daleks_email" in function_names
    assert "send_webhook_notification_email" in function_names
    assert "send_comprobante_abono" in function_names
    assert "send_notificacion_admin_abono" in function_names


def test_load_dotenv_runs_before_create_app():
    """Verify load_dotenv() is called before importing create_app in celery_app.py."""
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

