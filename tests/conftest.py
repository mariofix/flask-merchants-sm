"""Shared pytest fixtures for the test suite.

Creates a minimal Flask application backed by an in-memory SQLite database so
tests can exercise business logic without a running server, Redis, or external
payment providers.
"""

import uuid

import pytest
from flask import Flask

from app.database import db as _db


@pytest.fixture(scope="session")
def app():
    """Session-scoped Flask app with SQLite in-memory database."""
    test_app = Flask(__name__)
    test_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_RECORD_QUERIES=False,
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,
        # Silence Flask-Security password hashing cost in tests
        SECURITY_PASSWORD_HASH="plaintext",
        SECURITY_PASSWORD_SALT="test-salt",
        CELERY={"task_always_eager": True, "broker_url": "memory://", "result_backend": "cache+memory://"},
    )
    _db.init_app(test_app)
    with test_app.app_context():
        # Import all models so SQLAlchemy registers their metadata
        import app.model  # noqa: F401
        _db.create_all()
        yield test_app
        _db.drop_all()


@pytest.fixture()
def db_session(app):
    """Per-test database session; rolls back after each test."""
    with app.app_context():
        yield _db.session
        _db.session.rollback()
        # Truncate all tables so tests are isolated
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


@pytest.fixture()
def sample_user(db_session):
    """A minimal User row suitable for linking to an Apoderado."""
    from app.model import User
    user = User()
    user.email = "apoderado@test.cl"
    user.username = "apoderado_test"
    user.password = "password"
    user.active = True
    user.fs_uniquifier = str(uuid.uuid4())
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def sample_apoderado(db_session, sample_user):
    """An Apoderado linked to *sample_user* with one Alumno."""
    from app.model import Alumno, Apoderado
    apoderado = Apoderado()
    apoderado.nombre = "María González"
    apoderado.alumnos_registro = 1
    apoderado.usuario = sample_user
    apoderado.saldo_cuenta = 0
    db_session.add(apoderado)

    alumno = Alumno()
    alumno.slug = "juan-gonzalez-10"
    alumno.nombre = "Juan González"
    alumno.curso = "5A"
    alumno.apoderado = apoderado
    alumno.restricciones = []
    db_session.add(alumno)
    db_session.commit()
    return apoderado
