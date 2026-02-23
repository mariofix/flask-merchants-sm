"""Route-integrity tests for the /, /pos, and /apoderado blueprints.

Two categories of checks:

1. Every ``url_for()`` call found in an app template must reference an
   endpoint that is actually registered in the application.

2. An anonymous GET request to every non-parameterised route belonging
   to the ``core``, ``pos``, or ``apoderado_cliente`` blueprints must
   **not** produce a 5xx server error.
"""

import os
import re

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "app", "templates"
)

# Regex that captures the endpoint name in  url_for('some.endpoint', ...)
URL_FOR_RE = re.compile(r"url_for\s*\(\s*['\"]([^'\"]+)['\"]")

# Endpoints we never need to test (always-present Flask builtins)
SKIP_ENDPOINTS = {"static"}

# Blueprints whose routes are in scope for the HTTP health checks
IN_SCOPE_BLUEPRINTS = {"core", "pos", "apoderado_cliente"}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _collect_template_endpoints():
    """Yield ``(relative_template_path, endpoint_name)`` for every
    ``url_for()`` call found in any app template file."""
    for root, _, files in os.walk(TEMPLATE_DIR):
        for fname in sorted(files):
            if not (fname.endswith(".html") or fname.endswith(".j2")):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath) as fh:
                content = fh.read()
            for m in URL_FOR_RE.finditer(content):
                ep = m.group(1)
                if ep not in SKIP_ENDPOINTS:
                    yield os.path.relpath(fpath, TEMPLATE_DIR), ep


def _in_scope_get_routes(app):
    """Return URL rules that:
    * accept GET
    * have no dynamic path segments (so we can call them without guessing values)
    * belong to one of the IN_SCOPE_BLUEPRINTS
    """
    return [
        rule
        for rule in app.url_map.iter_rules()
        if "GET" in (rule.methods or set())
        and "<" not in rule.rule
        and rule.endpoint.split(".")[0] in IN_SCOPE_BLUEPRINTS
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Fixture — full app backed by SQLite in-memory
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def full_app():
    """Full Flask application with all blueprints registered, backed by an
    in-memory SQLite database.  Optional Flask-Security features are enabled
    so that their endpoints (e.g. ``security.register``) are present in the
    URL map for the url_for validation check."""
    # Set config via environment before create_app() reads it.
    env_defaults = {
        "FLASK_SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "FLASK_SECRET_KEY": "test-secret-link-check",
        "FLASK_SECURITY_PASSWORD_HASH": "plaintext",
        "FLASK_SECURITY_PASSWORD_SALT": "test-salt",
        "FLASK_WTF_CSRF_ENABLED": "False",
        "FLASK_TESTING": "True",
        "FLASK_CELERY": (
            '{"broker_url": "memory://", "result_backend": "cache+memory://"}'
        ),
        # Enable optional security features so their endpoints exist
        "FLASK_SECURITY_REGISTERABLE": "True",
        "FLASK_SECURITY_CHANGEABLE": "True",
    }
    for key, value in env_defaults.items():
        os.environ.setdefault(key, value)

    from app import create_app
    from app.database import db as _db

    _app = create_app()
    _app.config["TESTING"] = True
    _app.config["WTF_CSRF_ENABLED"] = False

    with _app.app_context():
        _db.create_all()
        yield _app
        _db.drop_all()


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestTemplateLinkIntegrity:
    """Every url_for() call in any app template must reference a registered
    endpoint.  A broken reference causes a BuildError at render time and
    returns a 500 to the user."""

    def test_no_broken_url_for_references(self, full_app):
        registered = {rule.endpoint for rule in full_app.url_map.iter_rules()}

        broken = [
            f"  {tmpl}: url_for({ep!r})"
            for tmpl, ep in _collect_template_endpoints()
            if ep not in registered
        ]

        if broken:
            # Deduplicate while preserving order
            seen, unique = set(), []
            for line in broken:
                if line not in seen:
                    seen.add(line)
                    unique.append(line)
            pytest.fail(
                "Templates reference non-existent endpoints "
                "(will cause 500 when rendered):\n" + "\n".join(unique)
            )


class TestRouteHealth:
    """Anonymous GET requests to every static (non-parameterised) route in the
    core, pos, and apoderado_cliente blueprints must not return a 5xx error."""

    def test_no_server_errors_on_anonymous_get(self, full_app):
        client = full_app.test_client()
        errors = []

        for rule in _in_scope_get_routes(full_app):
            resp = client.get(rule.rule, follow_redirects=False)
            if resp.status_code >= 500:
                errors.append(
                    f"  GET {rule.rule:<40} → {resp.status_code}"
                    f"  [{rule.endpoint}]"
                )

        if errors:
            pytest.fail(
                "Routes returned a server error on anonymous GET "
                "(check template rendering and missing login guard):\n"
                + "\n".join(errors)
            )
