"""flask_merchants - Flask/Quart extension for the merchants hosted-checkout SDK."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import merchants
from merchants.providers.dummy import DummyProvider

from flask_merchants.views import create_blueprint
from flask_merchants.version import __version__

__all__ = ["FlaskMerchants", "merchants_audit"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------
# ``merchants_audit`` is kept for backwards compatibility; it is an alias for
# the ``sm.audit`` logger configured by ``app.logging_config.configure_logging``
# at application startup.  A NullHandler is added so that messages logged
# before the app starts (e.g. during tests) are silently discarded.
# ---------------------------------------------------------------------------

logging.getLogger("sm.audit").addHandler(logging.NullHandler())
merchants_audit: logging.Logger = logging.getLogger("sm.audit")


def _is_quart_app(app) -> bool:
    """Return ``True`` when *app* is a :class:`quart.Quart` instance."""
    try:
        from quart import Quart

        return isinstance(app, Quart)
    except ImportError:
        return False


class FlaskMerchants:
    """Flask/Quart extension that wires the *merchants* SDK into an application.

    Usage - application factory pattern (all config passed to ``init_app``)::

        from flask import Flask
        from flask_merchants import FlaskMerchants

        merchants_ext = FlaskMerchants()          # extensions.py

        def create_app():
            app = Flask(__name__)
            db = SQLAlchemy(model_class=Base)
            merchants_ext.init_app(app, db=db, models=[Pagos], provider=MyProvider())
            return app

    Usage - application factory pattern (config split between constructor and ``init_app``)::

        merchants_ext = FlaskMerchants(db=db, models=[Pagos])   # extensions.py

        def create_app():
            app = Flask(__name__)
            merchants_ext.init_app(app)
            return app

    Usage - direct initialisation::

        from flask import Flask
        from flask_merchants import FlaskMerchants

        app = Flask(__name__)
        ext = FlaskMerchants(app)

    Usage - with a single custom SQLAlchemy model::

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

    Usage - with multiple custom SQLAlchemy models in the same app::

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

    Usage - with Quart (async)::

        from quart import Quart
        from flask_merchants import FlaskMerchants

        app = Quart(__name__)
        ext = FlaskMerchants(app)   # async blueprint selected automatically

    Usage - with multiple payment providers::

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

    ``MERCHANTS_URL_PREFIX``
        URL prefix for the blueprint (default: ``"/merchants"``).
    ``MERCHANTS_WEBHOOK_BASE_URL``
        Public scheme + domain used to build webhook URLs sent to providers
        (e.g. ``"https://example.com"``).  Required for
        :meth:`get_webhook_url`.  When empty, that method raises
        ``RuntimeError``.
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
        # Registered webhook event handlers; called after each /webhook/<provider> request.
        self._webhook_handlers: list = []

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
            admin: A :class:`flask_admin.Admin` instance.  When supplied and
                a *db* is configured, a :class:`~flask_admin.contrib.sqla.ModelView`
                with ``can_view_details=True`` is automatically registered for
                each payment model class under ``category="Merchants"``.  When
                no *db* is configured the in-memory
                :class:`~flask_merchants.contrib.admin.PaymentView` is used as
                a fallback.  :class:`~flask_merchants.contrib.admin.ProvidersView`
                is always added.
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

        app.config.setdefault("MERCHANTS_URL_PREFIX", "/merchants")
        app.config.setdefault("MERCHANTS_PAYMENT_VIEW_NAME", "Payments")
        app.config.setdefault("MERCHANTS_PROVIDER_VIEW_NAME", "Providers")
        app.config.setdefault("MERCHANTS_WEBHOOK_BASE_URL", "")

        self._webhook_base_url = app.config["MERCHANTS_WEBHOOK_BASE_URL"].rstrip("/")
        self._url_prefix = app.config["MERCHANTS_URL_PREFIX"]

        if _is_quart_app(app):
            from flask_merchants.quart_views import create_async_blueprint

            blueprint = create_async_blueprint(self)
        else:
            blueprint = create_blueprint(self)

        url_prefix = app.config["MERCHANTS_URL_PREFIX"]
        app.register_blueprint(blueprint, url_prefix=url_prefix)

        # Properly exempt webhook endpoints from Flask-WTF CSRF protection.
        # Payment providers POST to these URLs without CSRF tokens.
        # Flask-WTF 1.x does not honour a `csrf_exempt` attribute on view
        # functions; exemption must be registered via the CSRFProtect object.
        if "csrf" in app.extensions:
            csrf_ext = app.extensions["csrf"]
            bp_name = blueprint.name
            for view_name in ("webhook", "webhook_provider"):
                endpoint = f"{bp_name}.{view_name}"
                view_fn = app.view_functions.get(endpoint)
                if view_fn is not None:
                    csrf_ext.exempt(view_fn)

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
        logger.debug("__init__.py: FlaskMerchants.get_client called with provider_key=%r", provider_key)
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

    def get_webhook_url(self, provider: str) -> str:
        """Build the full webhook URL for *provider*.

        Uses ``MERCHANTS_WEBHOOK_BASE_URL`` (scheme + domain) combined with
        the blueprint prefix and ``/webhook/<provider>`` path.

        Raises:
            RuntimeError: If ``MERCHANTS_WEBHOOK_BASE_URL`` is not configured.

        Example::

            url = ext.get_webhook_url("khipu")
            # -> "https://example.com/merchants/webhook/khipu"
        """
        logger.debug("__init__.py: FlaskMerchants.get_webhook_url called with provider=%r", provider)
        if not self._webhook_base_url:
            raise RuntimeError(
                "MERCHANTS_WEBHOOK_BASE_URL is not configured. "
                "Set it to the public scheme+domain, e.g. 'https://example.com'."
            )
        url = f"{self._webhook_base_url}{self._url_prefix}/webhook/{provider}"
        logger.debug("__init__.py: FlaskMerchants.get_webhook_url result=%r", url)
        return url

    def add_webhook_handler(self, handler) -> None:
        """Register a callable invoked after each ``/webhook/<provider>`` request.

        The callable receives a single :class:`~merchants.models.WebhookEvent`
        argument.  Multiple handlers can be registered; they are called in
        registration order.  Any exception raised by a handler is silently
        swallowed so that a failing handler never prevents Khipu (or any other
        provider) from receiving a ``200`` response.

        Example::

            @flask_merchants.add_webhook_handler
            def on_payment(event):
                if event.state.value == "succeeded":
                    ...

        """
        self._webhook_handlers.append(handler)
        return handler  # allow use as a decorator

    def enable_webhook_notifications(
        self,
        admin_emails_fn: Callable[[], list[str]],
        send_fn: Callable[..., Any] | None = None,
    ) -> None:
        """Enable automatic email notifications to admin users on webhook events.

        When enabled, every incoming webhook triggers an email to the
        addresses returned by *admin_emails_fn* containing:

        * **provider** – the provider slug (e.g. ``"khipu"``)
        * **transaction** – the ``payment_id`` from the parsed event
        * **headers** – the full HTTP request headers (JSON)
        * **body** – the full HTTP request body (JSON)

        Args:
            admin_emails_fn: A callable that returns a list of email
                addresses.  Called at notification time so the list is
                always up-to-date.  Example::

                    def get_admin_emails():
                        role = db.session.execute(
                            db.select(Role).filter_by(name="admin")
                        ).scalar_one_or_none()
                        if not role:
                            return []
                        return [u.email for u in role.users if u.email]

            send_fn: An optional callable used to deliver the email.
                It receives a single ``dict`` argument with keys
                ``subject``, ``body``, ``to`` (list of addresses),
                ``provider``, ``transaction``, ``headers_json``, and
                ``body_json``.  When omitted, the extension sends via
                ``flask_mailman.EmailMessage`` synchronously inside the
                request (suitable for development; production apps should
                pass a Celery task wrapper).

        Example::

            flask_merchants.enable_webhook_notifications(
                admin_emails_fn=get_admin_emails,
                send_fn=lambda info: send_webhook_email_task.delay(info),
            )
        """
        self._webhook_notify_admin_emails_fn = admin_emails_fn
        self._webhook_notify_send_fn = send_fn
        self.add_webhook_handler(self._webhook_notification_handler)

    def _webhook_notification_handler(self, event) -> None:
        """Built-in handler that emails admins with raw webhook data."""
        from flask import request as flask_request

        admin_emails_fn = getattr(self, "_webhook_notify_admin_emails_fn", None)
        if admin_emails_fn is None:
            return

        try:
            admin_emails = admin_emails_fn()
        except Exception:  # noqa: BLE001
            merchants_audit.exception("webhook_notification: failed to resolve admin emails")
            return
        if not admin_emails:
            return

        headers_dict = dict(flask_request.headers)
        try:
            headers_json = json.dumps(headers_dict, indent=2, default=str)
        except (TypeError, ValueError):
            headers_json = str(headers_dict)

        raw_body = flask_request.get_data(as_text=True)
        try:
            body_parsed = json.loads(raw_body)
            body_json = json.dumps(body_parsed, indent=2, default=str)
        except (json.JSONDecodeError, TypeError, ValueError):
            body_json = raw_body

        provider = event.provider
        transaction = event.payment_id or ""

        subject = f"[webhook] {provider} — {transaction or 'no-id'}"
        body_text = (
            f"provider: {provider}\n"
            f"transaction: {transaction}\n"
            f"headers:\n{headers_json}\n\n"
            f"body:\n{body_json}\n"
        )

        notification_info = {
            "subject": subject,
            "body": body_text,
            "to": admin_emails,
            "provider": provider,
            "transaction": transaction,
            "headers_json": headers_json,
            "body_json": body_json,
        }

        send_fn = getattr(self, "_webhook_notify_send_fn", None)
        try:
            if send_fn is not None:
                send_fn(notification_info)
            else:
                self._send_webhook_notification_default(notification_info)
        except Exception:  # noqa: BLE001
            merchants_audit.exception(
                "webhook_notification: failed to send notification email"
            )

    @staticmethod
    def _send_webhook_notification_default(info: dict) -> None:
        """Fallback email sender using Flask-Mailman (synchronous)."""
        try:
            from flask_mailman import EmailMessage
        except ImportError:
            logger.warning(
                "flask_mailman not installed; cannot send webhook notification email"
            )
            return

        msg = EmailMessage(
            subject=info["subject"],
            body=info["body"],
            to=info["to"],
        )
        msg.send()
        merchants_audit.info(
            "webhook_notification_sent: to=%r subject=%r",
            info["to"],
            info["subject"],
        )

    def _dispatch_webhook_event(self, event) -> None:
        """Invoke all registered webhook handlers for *event*.

        Errors are caught individually so one failing handler does not stop
        the others from running.
        """
        logger.debug(
            "__init__.py: FlaskMerchants._dispatch_webhook_event called with event_type=%r payment_id=%r",
            event.event_type, event.payment_id,
        )
        for handler in self._webhook_handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001
                merchants_audit.exception(
                    "webhook_handler_error: handler=%r event_type=%r payment_id=%r",
                    handler,
                    event.event_type,
                    event.payment_id,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_client(self, provider_key: str) -> merchants.Client:
        """Create a :class:`merchants.Client` for the given *provider_key*."""
        return merchants.Client(provider=provider_key)

    def _get_model_classes(self) -> list:
        """Return the list of all registered model classes.

        Raises ``RuntimeError`` when no models have been registered.
        """
        if self._models:
            return self._models
        raise RuntimeError(
            "No payment model classes registered. Pass models=[YourPaymentModel] "
            "to FlaskMerchants() or init_app()."
        )

    @property
    def _payment_model(self):
        """Return the *default* model class (first in the list)."""
        return self._get_model_classes()[0]

    # ------------------------------------------------------------------
    # Payment creation (preferred API)
    # ------------------------------------------------------------------

    def create_payment(
        self,
        *,
        amount,
        currency: str,
        provider: str,
        success_url: str,
        cancel_url: str,
        email: str | None = None,
        extra_args: dict | None = None,
        merchants_id: str | None = None,
        request_context: dict | None = None,
        model_class=None,
    ):
        """Create a payment via the provider and persist it.

        This is a convenience wrapper around ``model_class.create()`` for
        callers that have the extension instance but not the model class.

        All arguments are forwarded to :meth:`PaymentMixin.create`.  See
        that method's docstring for full parameter documentation.

        Args:
            model_class: The model class to use.  Defaults to the first
                registered model (or the built-in Payment).

        Returns:
            The persisted payment instance.
        """
        cls = model_class if model_class is not None else self._payment_model
        return cls.create(
            amount=amount,
            currency=currency,
            provider=provider,
            success_url=success_url,
            cancel_url=cancel_url,
            email=email,
            extra_args=extra_args,
            merchants_id=merchants_id,
            request_context=request_context,
        )

    # ------------------------------------------------------------------
    # Payment store helpers (legacy — prefer Payment.create() / payment.refund())
    # ------------------------------------------------------------------

    def save_session(
        self,
        session: merchants.CheckoutSession,
        *,
        model_class=None,
        request_payload: dict | None = None,
    ) -> None:
        """Persist a :class:`~merchants.CheckoutSession`.

        .. deprecated::
            Prefer :meth:`PaymentMixin.create` which handles the full
            lifecycle (provider call + persistence) in a single step.

        When a SQLAlchemy *db* was provided the record is saved to the
        database; otherwise it is kept in the in-memory store.

        Args:
            session: The checkout session to persist.
            model_class: The model class to store the record in.
                Defaults to the first registered model.  Use this when
                you have multiple models registered and need to direct a
                payment to a specific table.
            request_payload: The data dict that was sent to the provider.
                When provided it is serialised as JSON and stored on the
                record.  Defaults to an empty dict.
        """
        import uuid as _uuid

        logger.debug(
            "__init__.py: FlaskMerchants.save_session called with session_id=%s provider=%s",
            session.session_id, session.provider,
        )
        # session.raw holds the provider's raw response; guard against non-dict types
        response_raw = session.raw if isinstance(session.raw, dict) else {}
        if session.redirect_url:
            response_raw.setdefault("redirect_url", session.redirect_url)
        req_payload = request_payload or {}
        merchants_id = str(_uuid.uuid4())

        data = {
            "merchants_id": merchants_id,
            "transaction_id": session.session_id,
            "provider": session.provider,
            "amount": str(session.amount),
            "currency": session.currency,
            "state": "pending",
            "request_payload": req_payload,
            "response_payload": response_raw,
        }

        if self._db is not None:
            cls = model_class if model_class is not None else self._payment_model
            record = cls(
                merchants_id=merchants_id,
                transaction_id=session.session_id,
                provider=session.provider,
                amount=session.amount,
                currency=session.currency,
                state="pending",
                request_payload=req_payload,
                response_payload=response_raw,
            )
            self._db.session.add(record)
            self._db.session.commit()

        # Always keep in-memory copy for fast look-up
        self._store[merchants_id] = data

    def get_session(self, payment_id: str) -> dict[str, Any] | None:
        """Return stored data for *payment_id*, or ``None``.

        Searches by ``merchants_id`` first, then by ``transaction_id``.
        When multiple models are registered, all of them are searched in
        registration order and the first match is returned.
        """
        if self._db is not None:
            for model_cls in self._get_model_classes():
                record = (
                    self._db.session.query(model_cls)
                    .filter_by(merchants_id=payment_id)
                    .first()
                )
                if record is not None:
                    return record.to_dict()
            # Fallback: search by transaction_id
            for model_cls in self._get_model_classes():
                record = (
                    self._db.session.query(model_cls)
                    .filter_by(transaction_id=payment_id)
                    .first()
                )
                if record is not None:
                    return record.to_dict()
            return None
        return self._store.get(payment_id)

    def update_state(self, payment_id: str, state: str) -> bool:
        """Update the stored state for *payment_id*. Returns ``True`` on success.

        Searches by ``merchants_id`` first, then by ``transaction_id``.

        .. deprecated::
            Prefer ``payment.state = "..."`` with a direct commit, or
            ``payment.refund()`` / ``payment.cancel()`` for common transitions.

        When multiple models are registered, all of them are searched in
        registration order; the first match is updated.
        """
        logger.debug("__init__.py: FlaskMerchants.update_state called with payment_id=%s state=%r", payment_id, state)
        if self._db is not None:
            record = None
            for model_cls in self._get_model_classes():
                record = (
                    self._db.session.query(model_cls)
                    .filter_by(merchants_id=payment_id)
                    .first()
                )
                if record is not None:
                    break
            # Fallback: search by transaction_id
            if record is None:
                for model_cls in self._get_model_classes():
                    record = (
                        self._db.session.query(model_cls)
                        .filter_by(transaction_id=payment_id)
                        .first()
                    )
                    if record is not None:
                        break
            if record is not None:
                record.state = state
                self._db.session.commit()
                mid = record.merchants_id
                if mid in self._store:
                    self._store[mid]["state"] = state
                return True
            # Not found in any model - fall back to in-memory
            if payment_id not in self._store:
                return False
            self._store[payment_id]["state"] = state
            return True

        if payment_id not in self._store:
            return False
        self._store[payment_id]["state"] = state
        return True

    def refund_session(self, payment_id: str) -> bool:
        """Mark *payment_id* as refunded. Returns ``True`` on success.

        .. deprecated:: Prefer ``payment.refund()`` on the payment instance.
        """
        return self.update_state(payment_id, "refunded")

    def cancel_session(self, payment_id: str) -> bool:
        """Mark *payment_id* as cancelled. Returns ``True`` on success.

        .. deprecated:: Prefer ``payment.cancel()`` on the payment instance.
        """
        return self.update_state(payment_id, "cancelled")

    def sync_from_provider(self, payment_id: str) -> dict[str, Any] | None:
        """Fetch live status from the provider and update the stored state.

        .. deprecated::
            Prefer ``payment.sync_from_provider()`` on the payment instance.

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

