"""flask_merchants – Flask/Quart extension for the merchants hosted-checkout SDK."""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from typing import Any

import merchants
from merchants.providers.dummy import DummyProvider

from flask_merchants.views import create_blueprint
from flask_merchants.version import __version__

__all__ = ["FlaskMerchants", "merchants_audit"]

# ---------------------------------------------------------------------------
# Audit logger – writes one rotating file per day, keeps 14 days of history.
# File name format: logs/merchants_audit.YYYY-MM-DD.log
# ---------------------------------------------------------------------------

def _setup_audit_logger(log_dir: str = "logs") -> logging.Logger:
    """Return the ``merchants_audit`` logger, configuring it on first call."""
    logger = logging.getLogger("merchants_audit")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    os.makedirs(log_dir, exist_ok=True)

    base_path = os.path.join(log_dir, "merchants_audit.log")
    handler = TimedRotatingFileHandler(
        base_path,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=False,
    )
    # Append the date to the rotated files: merchants_audit.log.YYYY-MM-DD
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


merchants_audit: logging.Logger = _setup_audit_logger()


def _is_quart_app(app) -> bool:
    """Return ``True`` when *app* is a :class:`quart.Quart` instance."""
    try:
        from quart import Quart

        return isinstance(app, Quart)
    except ImportError:
        return False


class FlaskMerchants:
    """Flask/Quart extension that wires the *merchants* SDK into an application.

    Usage – application factory pattern (all config passed to ``init_app``)::

        from flask import Flask
        from flask_merchants import FlaskMerchants

        merchants_ext = FlaskMerchants()          # extensions.py

        def create_app():
            app = Flask(__name__)
            db = SQLAlchemy(model_class=Base)
            merchants_ext.init_app(app, db=db, models=[Pagos], provider=MyProvider())
            return app

    Usage – application factory pattern (config split between constructor and ``init_app``)::

        merchants_ext = FlaskMerchants(db=db, models=[Pagos])   # extensions.py

        def create_app():
            app = Flask(__name__)
            merchants_ext.init_app(app)
            return app

    Usage – direct initialisation::

        from flask import Flask
        from flask_merchants import FlaskMerchants

        app = Flask(__name__)
        ext = FlaskMerchants(app)

    Usage – with SQLAlchemy (Flask-SQLAlchemy 3.x)::

        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from flask_merchants import FlaskMerchants
        from flask_merchants.models import Base

        db = SQLAlchemy(model_class=Base)
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///payments.db"
        ext = FlaskMerchants(app, db=db)
        db.init_app(app)

    Usage – with a single custom SQLAlchemy model::

        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from sqlalchemy import Integer
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
        from flask_merchants import FlaskMerchants
        from flask_merchants.models import PaymentMixin

        class Base(DeclarativeBase):
            pass

        db = SQLAlchemy(model_class=Base)

        class Pagos(PaymentMixin, db.Model):
            __tablename__ = "pagos"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        app = Flask(__name__)
        ext = FlaskMerchants(app, db=db, models=[Pagos])

    Usage – with multiple custom SQLAlchemy models in the same app::

        class Pagos(PaymentMixin, db.Model):
            __tablename__ = "pagos"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        class Paiements(PaymentMixin, db.Model):
            __tablename__ = "paiements"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        ext = FlaskMerchants(app, db=db, models=[Pagos, Paiements])

        # Direct a checkout to a specific model:
        session = ext.client.payments.create_checkout(...)
        ext.save_session(session, model_class=Pagos)
        ext.save_session(session2, model_class=Paiements)

        # get_session / update_state search across all models automatically.
        # all_sessions() returns records from all models combined.
        # all_sessions(model_class=Pagos) returns only Pagos records.

    Usage – with Quart (async)::

        from quart import Quart
        from flask_merchants import FlaskMerchants

        app = Quart(__name__)
        ext = FlaskMerchants(app)   # async blueprint selected automatically

    Usage – with multiple payment providers::

        import merchants
        from merchants.providers.dummy import DummyProvider

        # Register providers into the merchants global registry before init.
        merchants.register_provider(DummyProvider())
        # merchants.register_provider(StripeProvider(api_key="sk_test_..."))

        app = Flask(__name__)
        ext = FlaskMerchants(app)

        # All registered providers are now available.
        # In checkout, pass a ``provider`` field to select one:
        # POST /merchants/checkout  {"amount": "9.99", "currency": "USD", "provider": "dummy"}
        # GET  /merchants/providers  -> lists all registered provider keys

    Configuration keys (set on ``app.config``):

    ``MERCHANTS_WEBHOOK_SECRET``
        HMAC-SHA256 secret used to verify incoming webhook signatures.
        When ``None`` (default) signature verification is skipped.
    ``MERCHANTS_URL_PREFIX``
        URL prefix for the blueprint (default: ``"/merchants"``).
    """

    def __init__(self, app=None, *, provider=None, providers=None, db=None, model=None, models=None, admin=None) -> None:
        self._provider = provider
        self._providers: list = list(providers) if providers is not None else []
        self._db = db
        # Accept model= (singular) as a convenience alias for models=[model]
        if model is not None and models is None:
            models = [model]
        self._models: list = list(models) if models is not None else []
        self._admin = admin
        self._client: merchants.Client | None = None
        # Local cache: provider key -> merchants.Client
        self._clients: dict[str, merchants.Client] = {}
        # Simple in-memory payment store: {payment_id: dict}
        # Used when no SQLAlchemy db is provided.
        self._store: dict[str, dict[str, Any]] = {}

        if app is not None:
            self.init_app(app)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_app(
        self,
        app,
        *,
        provider=None,
        providers=None,
        db=None,
        model=None,
        models=None,
        admin=None,
    ) -> None:
        """Initialise the extension against *app* (Flask or Quart).

        All keyword arguments are optional.  When supplied they **override**
        the corresponding values that were passed to :meth:`__init__`, which
        enables the full application-factory pattern where configuration is
        deferred to ``init_app``::

            # extensions.py
            merchants_ext = FlaskMerchants()

            # app_factory.py
            def create_app():
                app = Flask(__name__)
                db = SQLAlchemy(model_class=Base)
                merchants_ext.init_app(app, db=db, models=[Pagos], provider=MyProvider())
                return app

        Args:
            app: The Flask (or Quart) application instance.
            provider: A single :class:`~merchants.Provider` instance to use as
                the default provider.  Overrides the value passed to ``__init__``.
            providers: A list of :class:`~merchants.Provider` instances to
                register.  Overrides the value passed to ``__init__``.
            db: A Flask-SQLAlchemy ``SQLAlchemy`` instance.  When supplied,
                payment records are persisted to the database.  Overrides the
                value passed to ``__init__``.
            models: A list of SQLAlchemy model classes (each mixing in
                :class:`~flask_merchants.models.PaymentMixin`).  Overrides the
                value passed to ``__init__``.
            admin: A :class:`flask_admin.Admin` instance.  When supplied,
                :class:`~flask_merchants.contrib.admin.PaymentView` and
                :class:`~flask_merchants.contrib.admin.ProvidersView` are
                automatically registered under ``category="Merchants"``.
                Overrides the value passed to ``__init__``.

        Any providers supplied via *provider* / *providers* are registered into
        the ``merchants`` global registry so that they become discoverable via
        :func:`merchants.list_providers`.

        If no providers are registered at all (neither explicitly passed nor
        pre-registered externally) a :class:`~merchants.providers.dummy.DummyProvider`
        is registered as a safe default for local development.
        """
        # Update stored config when non-None values are passed.
        if provider is not None:
            self._provider = provider
        if providers is not None:
            self._providers = list(providers)
        if db is not None:
            self._db = db
        # Accept model= (singular) as a convenience alias for models=[model]
        if model is not None and models is None:
            models = [model]
        if models is not None:
            self._models = list(models)
        if admin is not None:
            self._admin = admin
        # Register explicitly-supplied providers into the merchants registry.
        all_providers: list = list(self._providers)
        if self._provider is not None:
            all_providers.insert(0, self._provider)
        for p in all_providers:
            merchants.register_provider(p)

        # Fall back to DummyProvider when nothing has been registered yet.
        if not merchants.list_providers():
            merchants.register_provider(DummyProvider())

        # Default client: first explicitly-supplied provider, or first in registry.
        default_key = all_providers[0].key if all_providers else merchants.list_providers()[0]
        self._client = self._make_client(default_key)

        app.config.setdefault("MERCHANTS_WEBHOOK_SECRET", None)
        app.config.setdefault("MERCHANTS_URL_PREFIX", "/merchants")
        app.config.setdefault("MERCHANTS_PAYMENT_VIEW_NAME", "Payments")
        app.config.setdefault("MERCHANTS_PROVIDER_VIEW_NAME", "Providers")

        if _is_quart_app(app):
            from flask_merchants.quart_views import create_async_blueprint

            blueprint = create_async_blueprint(self)
        else:
            blueprint = create_blueprint(self)

        url_prefix = app.config["MERCHANTS_URL_PREFIX"]
        app.register_blueprint(blueprint, url_prefix=url_prefix)

        app.extensions["merchants"] = self

        # Auto-register admin views when an Admin instance was provided.
        if self._admin is not None:
            from flask_merchants.contrib.admin import register_admin_views

            register_admin_views(
                self._admin,
                self,
                payment_name=app.config["MERCHANTS_PAYMENT_VIEW_NAME"],
                provider_name=app.config["MERCHANTS_PROVIDER_VIEW_NAME"],
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def client(self) -> merchants.Client:
        """The underlying :class:`merchants.Client` instance (default provider)."""
        if self._client is None:
            raise RuntimeError(
                "FlaskMerchants extension not initialised. Call init_app(app) first."
            )
        return self._client

    def list_providers(self) -> list[str]:
        """Return the keys of all providers currently registered in the *merchants* SDK.

        This always reflects the live global registry, including providers
        registered externally after :meth:`init_app` was called.

        Example::

            ext.list_providers()  # -> ["dummy", "stripe"]
        """
        return merchants.list_providers()

    def get_client(self, provider_key: str | None = None) -> merchants.Client:
        """Return the :class:`merchants.Client` for *provider_key*.

        The client is looked up from the *merchants* global registry by the
        provider's :attr:`~merchants.Provider.key` string (e.g. ``"dummy"``,
        ``"stripe"``).  Clients are cached locally after the first lookup.

        When *provider_key* is ``None`` the default client (set at
        :meth:`init_app` time) is returned.

        Raises:
            KeyError: If *provider_key* is not found in the merchants registry.

        Example::

            client = ext.get_client("stripe")
            session = client.payments.create_checkout(...)
        """
        if provider_key is None:
            return self.client
        if provider_key not in self._clients:
            try:
                self._clients[provider_key] = self._make_client(provider_key)
            except KeyError:
                raise KeyError(
                    f"Unknown provider: {provider_key!r}. "
                    f"Available: {merchants.list_providers()}"
                )
        return self._clients[provider_key]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_client(self, provider_key: str) -> merchants.Client:
        """Create a :class:`merchants.Client` for the given *provider_key*."""
        return merchants.Client(provider=provider_key)

    def _get_model_classes(self) -> list:
        """Return the list of all registered model classes.

        Falls back to the built-in :class:`~flask_merchants.models.Payment`
        when no custom models have been registered.
        """
        if self._models:
            return self._models
        from flask_merchants.models import Payment
        return [Payment]

    @property
    def _payment_model(self):
        """Return the *default* model class (first in the list)."""
        return self._get_model_classes()[0]

    # ------------------------------------------------------------------
    # Payment store helpers
    # ------------------------------------------------------------------

    def save_session(
        self,
        session: merchants.CheckoutSession,
        *,
        model_class=None,
        request_payload: dict | None = None,
    ) -> None:
        """Persist a :class:`~merchants.CheckoutSession`.

        When a SQLAlchemy *db* was provided the record is saved to the
        database; otherwise it is kept in the in-memory store.

        Args:
            session: The checkout session to persist.
            model_class: The model class to store the record in.
                Defaults to the first registered model (or the built-in
                :class:`~flask_merchants.models.Payment`).  Use this when
                you have multiple models registered and need to direct a
                payment to a specific table.
            request_payload: The data dict that was sent to the provider.
                When provided it is serialised as JSON and stored on the
                record.  Defaults to an empty dict.
        """
        # session.raw holds the provider's raw response; guard against non-dict types
        response_raw = session.raw if isinstance(session.raw, dict) else {}
        req_payload = request_payload or {}

        data = {
            "session_id": session.session_id,
            "redirect_url": session.redirect_url,
            "provider": session.provider,
            "amount": str(session.amount),
            "currency": session.currency,
            "metadata": session.metadata,
            "state": "pending",
            "request_payload": req_payload,
            "response_payload": response_raw,
        }

        if self._db is not None:
            cls = model_class if model_class is not None else self._payment_model
            record = cls(
                session_id=session.session_id,
                redirect_url=session.redirect_url,
                provider=session.provider,
                amount=session.amount,
                currency=session.currency,
                state="pending",
                metadata_json=session.metadata or {},
                request_payload=req_payload,
                response_payload=response_raw,
            )
            self._db.session.add(record)
            self._db.session.commit()

        # Always keep in-memory copy for fast look-up
        self._store[session.session_id] = data

    def get_session(self, payment_id: str) -> dict[str, Any] | None:
        """Return stored data for *payment_id*, or ``None``.

        When multiple models are registered, all of them are searched in
        registration order and the first match is returned.
        """
        if self._db is not None:
            for model_cls in self._get_model_classes():
                record = (
                    self._db.session.query(model_cls)
                    .filter_by(session_id=payment_id)
                    .first()
                )
                if record is not None:
                    return record.to_dict()
            return None
        return self._store.get(payment_id)

    def update_state(self, payment_id: str, state: str) -> bool:
        """Update the stored state for *payment_id*. Returns ``True`` on success.

        When multiple models are registered, all of them are searched in
        registration order; the first match is updated.
        """
        if self._db is not None:
            for model_cls in self._get_model_classes():
                record = (
                    self._db.session.query(model_cls)
                    .filter_by(session_id=payment_id)
                    .first()
                )
                if record is not None:
                    record.state = state
                    self._db.session.commit()
                    if payment_id in self._store:
                        self._store[payment_id]["state"] = state
                    return True
            # Not found in any model – fall back to in-memory
            if payment_id not in self._store:
                return False
            self._store[payment_id]["state"] = state
            return True

        if payment_id not in self._store:
            return False
        self._store[payment_id]["state"] = state
        return True

    def refund_session(self, payment_id: str) -> bool:
        """Mark *payment_id* as refunded. Returns ``True`` on success."""
        return self.update_state(payment_id, "refunded")

    def cancel_session(self, payment_id: str) -> bool:
        """Mark *payment_id* as cancelled. Returns ``True`` on success."""
        return self.update_state(payment_id, "cancelled")

    def sync_from_provider(self, payment_id: str) -> dict[str, Any] | None:
        """Fetch live status from the provider and update the stored state.

        Returns the updated stored record, or ``None`` if *payment_id* is not
        found or the provider call fails.
        """
        stored = self.get_session(payment_id)
        if stored is None:
            return None
        try:
            status = self.client.payments.get(payment_id)
        except Exception:  # noqa: BLE001
            return None
        self.update_state(payment_id, status.state.value)
        stored["state"] = status.state.value
        return stored

    def all_sessions(self, *, model_class=None) -> list[dict[str, Any]]:
        """Return all stored payment sessions.

        Args:
            model_class: When provided, return records only from that model
                class.  When omitted, records from **all** registered models
                are returned combined.
        """
        if self._db is not None:
            classes = [model_class] if model_class is not None else self._get_model_classes()
            result = []
            for cls in classes:
                result.extend(r.to_dict() for r in self._db.session.query(cls).all())
            return result
        return list(self._store.values())

