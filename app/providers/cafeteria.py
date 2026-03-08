"""Cafetería provider - pago presencial en efectivo o tarjeta en la cafetería.

CafeteriaProvider handles cash/card payments made in person at the school
cafeteria.  The system creates a payment in ``processing`` state and does NOT
redirect the user to an external provider.

``merchants_id`` and ``transaction_id`` are always the same value — a code
with the ``cafe_`` prefix followed by 8 random alphanumeric characters.

Admin or POS staff authorize the payment via the data-manager Flask-Admin
action.  On approval the ``payment_object`` column is populated with the
payment's ``to_dict()`` output plus the saldo snapshot (before / after).
"""
from __future__ import annotations

import json
import logging
import random
import string
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

from merchants.models import CheckoutSession, PaymentState, PaymentStatus, WebhookEvent
from merchants.providers import Provider


def _rand_code(length: int = 8) -> str:
    """Generate a random alphanumeric code in uppercase."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class CafeteriaProvider(Provider):
    """Proveedor de pago presencial para la cafetería del colegio.

    El apoderado recibe un código QR y un código corto que presenta en la
    cafetería para pagar en efectivo o tarjeta.  El personal (admin/pos)
    aprueba el pago manualmente desde el panel.

    ``session_id`` (which becomes ``transaction_id`` in the mixin) always
    equals ``merchants_id`` — both use the ``cafe_XXXXXXXX`` format.
    """

    key = "cafeteria"
    name = "Cafetería"
    author = "SaborMirandiano"
    version = "1.0.0"
    description = "Pago presencial en efectivo o tarjeta en la cafetería del colegio."
    url = ""

    def create_checkout(
        self,
        amount: Decimal,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, Any] | None = None,
        *,
        codigo: str | None = None,
        **kwargs: Any,
    ) -> CheckoutSession:
        logger.debug("cafeteria.py: CafeteriaProvider.create_checkout called with amount=%s currency=%s", amount, currency)
        # Use the caller-provided codigo (which matches merchants_id) so that
        # merchants_id == transaction_id for this internal provider.
        # Falls back to generating cafe_ + 8 random chars.
        session_id = codigo or f"cafe_{_rand_code(8)}"
        # Short display code for screen / QR
        display_code = _rand_code(6)
        return CheckoutSession(
            session_id=session_id,
            redirect_url=success_url,
            provider=self.key,
            amount=amount,
            currency=currency,
            metadata={"display_code": display_code},
            raw={"display_code": display_code},
            initial_state=PaymentState.PROCESSING,
        )

    def get_payment(self, payment_id: str) -> PaymentStatus:
        logger.debug("cafeteria.py: CafeteriaProvider.get_payment called with payment_id=%s", payment_id)
        # El estado real se gestiona manualmente en la base de datos.
        return PaymentStatus(
            payment_id=payment_id,
            state=PaymentState.PROCESSING,
            provider=self.key,
            raw={},
        )

    def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        logger.debug("cafeteria.py: CafeteriaProvider.parse_webhook called")
        try:
            data: dict[str, Any] = json.loads(payload)
        except ValueError:
            data = {}
        return WebhookEvent(
            event_id=data.get("event_id"),
            event_type="payment.cafeteria",
            payment_id=data.get("payment_id"),
            state=PaymentState.PROCESSING,
            provider=self.key,
            raw=data,
        )
