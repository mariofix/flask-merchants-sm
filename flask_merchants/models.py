"""SQLAlchemy ORM model for flask-merchants payments.

Usage with Flask-SQLAlchemy 3.x::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from flask_merchants.models import Base, Payment

    db = SQLAlchemy(model_class=Base)

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///payments.db"
    db.init_app(app)

    with app.app_context():
        db.create_all()

Or bring your own model by mixing in :class:`PaymentMixin`::

    from flask_sqlalchemy import SQLAlchemy
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from sqlalchemy import Integer
    from flask_merchants.models import PaymentMixin

    class Base(DeclarativeBase):
        pass

    db = SQLAlchemy(model_class=Base)

    class Pagos(PaymentMixin, db.Model):
        __tablename__ = "pagos"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

Then pass the model to FlaskMerchants::

    ext = FlaskMerchants(app, db=db, models=[Pagos])

Payment creation via the ``create()`` classmethod::

    payment = Pagos.create(
        amount=9990,
        currency="CLP",
        provider="khipu",
        success_url="https://example.com/ok",
        cancel_url="https://example.com/cancel",
        email="user@example.com",
    )
    # payment is already persisted with request/response payloads populated.
    # On provider failure, a record with state="failed" is stored.
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, Numeric, String, func, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

logger = logging.getLogger(__name__)


class PaymentMixin:
    """SQLAlchemy declarative mixin that adds all payment fields.

    Mix this into your own model class so that flask-merchants can store
    and retrieve payments using your table instead of the built-in
    :class:`Payment` model::

        class Pagos(PaymentMixin, db.Model):
            __tablename__ = "pagos"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

    All column definitions, :meth:`to_dict`, :meth:`create`, and
    :meth:`__repr__` are inherited from this mixin.  You can add extra
    columns or relationships as normal.

    Payment lifecycle
    -----------------
    Use the :meth:`create` classmethod to create a new payment.  It calls
    the provider, populates all fields (including request/response
    payloads), and persists the record in a single step.  Even if the
    provider call fails, a record with ``state="failed"`` is created so
    no payment attempt goes untracked.

    After creation, use :meth:`refund`, :meth:`cancel`, or
    :meth:`sync_from_provider` to manage the payment's lifecycle.

    The ``provider`` field is immutable after creation — changing it will
    raise a ``RuntimeError``.
    """

    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    redirect_url: Mapped[str] = mapped_column(String(2048))
    provider: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    currency: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(32), default="pending")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    extra_args: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    provider_payment_object: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    #: Valid lifecycle state values accepted by the model.
    VALID_STATES: frozenset[str] = frozenset(
        ("pending", "processing", "succeeded", "failed", "cancelled", "refunded", "unknown")
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @validates("state")
    def validate_state(self, key: str, value: str) -> str:
        """Reject unknown state values at the SQLAlchemy attribute level.

        SQLAlchemy calls this automatically whenever ``state`` is assigned,
        including during bulk operations and direct ORM updates - giving a
        single, reliable place to enforce the payment lifecycle invariant
        regardless of which code path triggered the change.

        Raises:
            ValueError: If *value* is not one of the recognised lifecycle
                states defined in :attr:`VALID_STATES`.
        """
        if value not in self.VALID_STATES:
            raise ValueError(
                f"Invalid payment state {value!r}. "
                f"Allowed values: {', '.join(sorted(self.VALID_STATES))}."
            )
        return value

    @validates("provider")
    def validate_provider_immutable(self, key: str, value: str) -> str:
        """Prevent changing the provider after the payment has been persisted.

        Changing the provider slug after creation is neither supported nor
        recommended — the payment is bound to its provider's session and
        switching would leave the record in an inconsistent state.

        Raises:
            RuntimeError: If the provider is changed on a persisted record.
        """
        insp = inspect(self, raiseerr=False)
        if insp is not None and not insp.pending and not insp.transient:
            current = insp.attrs.provider.loaded_value
            if current is not None and current != value:
                warnings.warn(
                    f"Changing the payment provider from {current!r} to {value!r} "
                    f"is neither supported nor recommended. The payment is bound "
                    f"to its original provider.",
                    stacklevel=2,
                )
                raise RuntimeError(
                    f"Cannot change payment provider from {current!r} to {value!r}. "
                    f"A payment is permanently bound to its provider after creation."
                )
        return value

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _get_ext(cls):
        """Retrieve the FlaskMerchants extension from the current app context.

        Raises:
            RuntimeError: If called outside a Flask application context or
                the FlaskMerchants extension is not initialised.
        """
        from flask import current_app

        try:
            ext = current_app.extensions["merchants"]
        except (RuntimeError, KeyError) as exc:
            raise RuntimeError(
                "PaymentMixin requires a Flask application context with "
                "FlaskMerchants initialised. Ensure you are inside an app "
                "context and that FlaskMerchants.init_app() has been called."
            ) from exc
        return ext

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        amount: Decimal | int | str,
        currency: str,
        provider: str,
        success_url: str,
        cancel_url: str,
        email: str | None = None,
        metadata: dict[str, Any] | None = None,
        extra_args: dict[str, Any] | None = None,
        session_id_override: str | None = None,
        request_context: dict[str, Any] | None = None,
    ):
        """Create a payment record by calling the provider and persisting the result.

        This is the primary entry point for creating payments.  It:

        1. Calls the provider's ``create_checkout`` with the given parameters
           (``extra_args`` are unpacked as ``**kwargs`` into the provider call).
        2. Populates all columns from the provider's ``CheckoutSession``
           response, including ``request_payload`` and ``response_payload``.
        3. Persists the record to the database and commits.

        If the provider call fails, a record with ``state="failed"`` is still
        created so no payment attempt goes untracked.  Failed payments cannot
        be re-processed — create a new payment instead.

        Args:
            amount: Payment amount.
            currency: ISO-4217 currency code (e.g. ``"CLP"``, ``"USD"``).
            provider: Provider slug (e.g. ``"khipu"``, ``"cafeteria"``).
            success_url: URL to redirect to on successful payment.
            cancel_url: URL to redirect to on cancelled payment.
            email: Optional payer email address.
            metadata: App-level metadata stored in ``metadata_json``.
                This is NOT sent to the provider.
            extra_args: Provider-specific keyword arguments unpacked into
                ``create_checkout()``.  E.g. ``{"expires_date": "...", "timeout": 30}``.
                Stored in the ``extra_args`` column for audit purposes.
            session_id_override: When set, used as the local ``session_id``
                instead of the provider-generated one.  The provider's original
                ``session_id`` is stored in ``metadata_json["provider_session_id"]``.
            request_context: Additional context merged into ``request_payload``
                for audit trail (e.g. ``{"abono_codigo": "..."}``).

        Returns:
            The persisted payment instance (with ``id`` assigned).

        Raises:
            KeyError: If the provider slug is not registered.
            Any provider exception is caught, recorded, and the failed
            payment is persisted.  The original exception is re-raised.
        """
        ext = cls._get_ext()
        amount = Decimal(str(amount))
        meta = dict(metadata or {})
        provider_extra = dict(extra_args or {})
        req_context = dict(request_context or {})

        # Auto-inject webhook notify_url if configured for this provider.
        # This is a provider concern, so it goes into extra_args (not metadata).
        try:
            notify_url = ext.get_webhook_url(provider)
            provider_extra.setdefault("notify_url", notify_url)
        except RuntimeError:
            pass

        # Build the request payload for audit
        request_payload = {
            "amount": str(amount),
            "currency": currency,
            "provider": provider,
            "success_url": success_url,
            "cancel_url": cancel_url,
            **req_context,
        }
        if email:
            request_payload["email"] = email
        if provider_extra:
            request_payload["extra_args"] = provider_extra

        import uuid

        try:
            client = ext.get_client(provider)
            session = client.payments.create_checkout(
                amount=amount,
                currency=currency,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=meta,
                **provider_extra,
            )

            # Determine session_id: override or provider-generated
            local_session_id = session.session_id
            stored_meta = dict(meta)
            if session_id_override:
                stored_meta["provider_session_id"] = session.session_id
                local_session_id = session_id_override

            response_raw = session.raw if isinstance(session.raw, dict) else {}

            record = cls(
                session_id=local_session_id,
                redirect_url=session.redirect_url,
                provider=session.provider,
                amount=session.amount,
                currency=session.currency,
                state=session.initial_state.value,
                email=email,
                metadata_json=session.metadata or stored_meta,
                extra_args=provider_extra,
                request_payload=request_payload,
                response_payload=response_raw,
            )

        except Exception as exc:
            # Provider call failed — persist a failed record
            logger.error(
                "Payment creation failed for provider=%r amount=%s: %s",
                provider, amount, exc,
            )
            failed_session_id = session_id_override or f"failed_{uuid.uuid4().hex[:16]}"
            record = cls(
                session_id=failed_session_id,
                redirect_url="",
                provider=provider,
                amount=amount,
                currency=currency,
                state="failed",
                email=email,
                metadata_json=meta,
                extra_args=provider_extra,
                request_payload=request_payload,
                response_payload={"error": str(exc), "error_type": type(exc).__name__},
            )
            ext._db.session.add(record)
            ext._db.session.commit()
            raise

        ext._db.session.add(record)
        ext._db.session.commit()

        logger.info(
            "Payment created: session_id=%s provider=%s amount=%s state=%s",
            record.session_id, record.provider, record.amount, record.state,
        )
        return record

    # ------------------------------------------------------------------
    # Instance methods
    # ------------------------------------------------------------------

    def refund(self):
        """Mark this payment as refunded.

        Returns:
            self, for method chaining.
        """
        ext = self._get_ext()
        self.state = "refunded"
        ext._db.session.commit()
        logger.info("Payment refunded: session_id=%s", self.session_id)
        return self

    def cancel(self):
        """Mark this payment as cancelled.

        Returns:
            self, for method chaining.
        """
        ext = self._get_ext()
        self.state = "cancelled"
        ext._db.session.commit()
        logger.info("Payment cancelled: session_id=%s", self.session_id)
        return self

    def sync_from_provider(self):
        """Fetch live status from the provider and update local state.

        Uses ``metadata_json["provider_session_id"]`` as the provider lookup
        key when available (for payments created with ``session_id_override``),
        otherwise uses ``session_id``.

        Returns:
            self, for method chaining.

        Raises:
            Exception: If the provider call fails.
        """
        ext = self._get_ext()
        provider_id = (self.metadata_json or {}).get(
            "provider_session_id", self.session_id
        )
        client = ext.get_client(self.provider)
        status = client.payments.get(provider_id)
        self.state = status.state.value
        self.response_payload = status.raw if isinstance(status.raw, dict) else {}
        self.provider_payment_object = status.model_dump(mode="json")
        ext._db.session.commit()
        logger.info(
            "Payment synced from provider: session_id=%s new_state=%s",
            self.session_id, self.state,
        )
        return self

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.session_id} state={self.state!r}>"

    def to_dict(self) -> dict:
        """Return a plain-dict representation (mirrors the in-memory store format)."""
        return {
            "session_id": self.session_id,
            "redirect_url": self.redirect_url,
            "provider": self.provider,
            "amount": f"{Decimal(self.amount):.2f}",
            "currency": self.currency,
            "state": self.state,
            "email": self.email,
            "metadata": self.metadata_json or {},
            "extra_args": self.extra_args or {},
            "request_payload": self.request_payload or {},
            "response_payload": self.response_payload or {},
            "provider_payment_object": self.provider_payment_object or {},
        }


class Base(DeclarativeBase):
    """Shared declarative base for flask-merchants models."""


class Payment(PaymentMixin, Base):
    """Built-in payment record backed by the ``payments`` table.

    Attributes:
        id: Auto-incrementing primary key.
        session_id: Provider-issued session/payment ID (unique).
        redirect_url: Hosted-checkout URL the user was redirected to.
        provider: Provider key string (e.g. ``"dummy"``, ``"stripe"``).
            Immutable after creation.
        amount: Payment amount as a fixed-precision decimal.
        currency: ISO-4217 currency code (e.g. ``"USD"``).
        state: Payment lifecycle state (``"pending"``, ``"succeeded"``, …).
        email: Optional payer email address.
        metadata_json: App-level metadata dict (not sent to the provider).
        extra_args: Provider-specific kwargs unpacked into ``create_checkout()``.
        request_payload: Data sent to the provider.
        response_payload: Raw response received from the provider.
        provider_payment_object: Full provider Payment object snapshot,
            updated by ``sync_from_provider()``.
        created_at: Record creation timestamp (UTC).
        updated_at: Record last-update timestamp (UTC).
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
