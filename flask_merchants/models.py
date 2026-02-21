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
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, JSON, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates


class PaymentMixin:
    """SQLAlchemy declarative mixin that adds all payment fields.

    Mix this into your own model class so that flask-merchants can store
    and retrieve payments using your table instead of the built-in
    :class:`Payment` model::

        class Pagos(PaymentMixin, db.Model):
            __tablename__ = "pagos"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

    All column definitions, :meth:`to_dict`, and :meth:`__repr__` are
    inherited from this mixin.  You can add extra columns or relationships
    as normal.
    """

    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    redirect_url: Mapped[str] = mapped_column(String(2048))
    provider: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    currency: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(32), default="pending")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
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

    @validates("state")
    def validate_state(self, key: str, value: str) -> str:
        """Reject unknown state values at the SQLAlchemy attribute level.

        SQLAlchemy calls this automatically whenever ``state`` is assigned,
        including during bulk operations and direct ORM updates – giving a
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
            "metadata": self.metadata_json or {},
            "request_payload": self.request_payload or {},
            "response_payload": self.response_payload or {},
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
        amount: Payment amount as a fixed-precision decimal.
        currency: ISO-4217 currency code (e.g. ``"USD"``).
        state: Payment lifecycle state (``"pending"``, ``"succeeded"``, …).
        metadata_json: Metadata dict passed at checkout.
        request_payload: Data sent to the provider.
        response_payload: Raw response received from the provider.
        created_at: Record creation timestamp (UTC).
        updated_at: Record last-update timestamp (UTC).
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
