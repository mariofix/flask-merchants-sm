"""SaldoProvider - pago automático con saldo de cuenta del apoderado."""
from __future__ import annotations

import json
import logging
import random
import string
import uuid
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

from merchants.models import CheckoutSession, PaymentState, PaymentStatus, WebhookEvent
from merchants.providers import Provider


def _rand_code(length: int = 8) -> str:
    """Generate a random alphanumeric code in uppercase."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class SaldoProvider(Provider):
    """Proveedor de pago con saldo de cuenta del apoderado.

    Autorización y validación son automáticas: si el apoderado tiene suficiente
    saldo, el pago se aprueba inmediatamente sin redirigir a un tercero.

    El payload de la solicitud incluye el modelo y propiedad que contiene el
    saldo a descontar (``model_property``).  La respuesta registra el saldo
    antes y después de la compra junto con un código único de transacción.
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
    ) -> CheckoutSession:
        logger.debug("saldo.py: SaldoProvider.create_checkout called with amount=%s currency=%s", amount, currency)
        meta = metadata or {}
        # Unique session identifier for this saldo transaction
        session_id = f"saldo_{_rand_code(12)}"
        # Short user-visible transaction confirmation code
        transaction_code = _rand_code(8)
        saldo_antes = int(meta.get("saldo_antes", 0))
        saldo_despues = saldo_antes - int(amount)

        return CheckoutSession(
            session_id=session_id,
            # Redirect immediately to success - no external gateway needed
            redirect_url=success_url,
            provider=self.key,
            amount=amount,
            currency=currency,
            metadata={
                **meta,
                "transaction_code": transaction_code,
                "saldo_antes": saldo_antes,
                "saldo_despues": saldo_despues,
            },
            raw={
                "transaction_code": transaction_code,
                "saldo_antes": saldo_antes,
                "saldo_despues": saldo_despues,
                # Which model property was debited - informational for audit trail
                "model_property": meta.get("model_property", "saldo_cuenta"),
                "apoderado_id": meta.get("apoderado_id"),
            },
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
