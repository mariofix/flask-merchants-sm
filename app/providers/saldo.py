"""SaldoProvider - pago automático con saldo de cuenta del apoderado.

SaldoProvider is enabled when ``Apoderado.saldo_cuenta`` is an integer > 0.
It is **only** available for Pedidos — never for Abonos.

The pedido.codigo should start with ``saldo_`` followed by 6 random
alphanumeric characters.

``request_payload`` stores: current_user id, apoderado id, saldo actual.
``response_payload`` stores: pedido.codigo, saldo_actual, nuevo_saldo.

The payment is stored as **completed** immediately since the saldo
deduction is certain.

Note: ``SchoolStaff.limite_cuenta = None`` does **not** mean unlimited
credit for SaldoProvider purposes — staff accounts are post-pay and
handled by the ``cuenta`` payment method instead.
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


def _rand_code(length: int = 6) -> str:
    """Generate a random alphanumeric code in uppercase."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class SaldoProvider(Provider):
    """Proveedor de pago con saldo de cuenta del apoderado.

    Autorización y validación son automáticas: si el apoderado tiene suficiente
    saldo, el pago se aprueba inmediatamente sin redirigir a un tercero.

    Only available for Pedidos.  Not available for Abonos (depositing money
    and paying with that same money makes no sense).

    ``session_id`` (which becomes ``transaction_id``) uses the ``saldo_``
    prefix + 6 random characters.
    """

    key = "saldo"
    name = "Saldo de Cuenta"
    author = "SaborMirandiano"
    version = "1.0.0"
    description = "Pago automático con saldo de cuenta del apoderado (autorización instantánea)."
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
    ) -> CheckoutSession:
        logger.debug("saldo.py: SaldoProvider.create_checkout called with amount=%s currency=%s", amount, currency)
        meta = metadata or {}
        # Use caller-provided codigo so merchants_id == transaction_id.
        # Falls back to saldo_ + 6 random chars.
        session_id = codigo or f"saldo_{_rand_code(6)}"

        saldo_actual = int(meta.get("saldo_actual", 0))
        nuevo_saldo = saldo_actual - int(amount)

        return CheckoutSession(
            session_id=session_id,
            redirect_url=success_url,
            provider=self.key,
            amount=amount,
            currency=currency,
            metadata={},
            raw={
                "pedido_codigo": meta.get("pedido_codigo", ""),
                "saldo_actual": saldo_actual,
                "nuevo_saldo": nuevo_saldo,
            },
            initial_state=PaymentState.SUCCEEDED,
        )

    def get_payment(self, payment_id: str) -> PaymentStatus:
        logger.debug("saldo.py: SaldoProvider.get_payment called with payment_id=%s", payment_id)
        # Saldo payments are approved immediately; state is always succeeded.
        return PaymentStatus(
            payment_id=payment_id,
            state=PaymentState.SUCCEEDED,
            provider=self.key,
            raw={},
        )

    def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        logger.debug("saldo.py: SaldoProvider.parse_webhook called")
        try:
            data: dict[str, Any] = json.loads(payload)
        except ValueError:
            data = {}
        return WebhookEvent(
            event_id=data.get("event_id"),
            event_type="payment.saldo",
            payment_id=data.get("payment_id"),
            state=PaymentState.SUCCEEDED,
            provider=self.key,
            raw=data,
        )
