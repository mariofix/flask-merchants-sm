"""Cafetería provider – pago presencial en efectivo o tarjeta en la cafetería."""
from __future__ import annotations

import json
import random
import string
from decimal import Decimal
from typing import Any

from merchants.models import CheckoutSession, PaymentState, PaymentStatus, WebhookEvent
from merchants.providers import Provider


def _rand_display_code(length: int = 6) -> str:
    """Genera un código corto alfanumérico en mayúsculas para mostrar al cliente."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class CafeteriaProvider(Provider):
    """Proveedor de pago presencial para la cafetería del colegio.

    El apoderado recibe un código QR y un código corto que presenta en la
    cafetería para pagar en efectivo o tarjeta.  El personal (admin/pos)
    aprueba el pago manualmente desde el panel de detalle del abono.
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
    ) -> CheckoutSession:
        meta = metadata or {}
        # Usar abono_codigo como session_id para poder buscarlo luego por abono.codigo
        session_id = meta.get("abono_codigo") or f"cafe_{_rand_display_code(12)}"
        # Código corto para mostrar en pantalla / QR
        display_code = _rand_display_code()
        return CheckoutSession(
            session_id=session_id,
            redirect_url=success_url,
            provider=self.key,
            amount=amount,
            currency=currency,
            metadata={**meta, "display_code": display_code},
            raw={"display_code": display_code},
        )

    def get_payment(self, payment_id: str) -> PaymentStatus:
        # El estado real se gestiona manualmente en la base de datos.
        return PaymentStatus(
            payment_id=payment_id,
            state=PaymentState.PROCESSING,
            provider=self.key,
            raw={},
        )

    def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
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
