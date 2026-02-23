"""PosController — CRUD and business logic for the POS module.

Route functions in routes.py are thin HTTP wrappers that parse the request,
delegate to this controller, and return a Flask response.  The controller
uses only SQLAlchemy (via ``db``) and plain Python — no ``request``,
``current_user``, or ``url_for`` calls — making every method independently
testable.
"""

from typing import Optional

from ..database import db
from ..model import Abono, Alumno, EstadoPedido, Payment, Pedido


class PosController:
    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_alumnos_sin_tag(self) -> list[Alumno]:
        """Return all Alumno records that have no NFC tag assigned."""
        return (
            db.session.execute(
                db.select(Alumno).filter_by(tag=None).order_by(Alumno.curso, Alumno.slug)
            )
            .scalars()
            .all()
        )

    def get_alumno_by_tag(self, serial: str) -> Optional[Alumno]:
        """Return the Alumno matching *serial* (case-insensitive), or ``None``."""
        return db.session.execute(
            db.select(Alumno).filter_by(tag=serial.upper())
        ).scalar_one_or_none()

    def get_abono_by_codigo(self, codigo: str) -> tuple:
        """Return ``(Abono, Payment, display_code)`` for *codigo*.

        The lookup first tries an exact match on ``Abono.codigo``, then
        falls back to matching ``Payment.metadata_json['display_code']``.
        Returns ``(None, None, "")`` when nothing is found.
        """
        abono = db.session.execute(
            db.select(Abono).filter_by(codigo=codigo)
        ).scalar_one_or_none()
        pago: Optional[Payment] = None

        if not abono:
            pagos = db.session.execute(
                db.select(Payment).where(Payment.metadata_json.isnot(None))
            ).scalars().all()
            for p in pagos:
                if (p.metadata_json or {}).get("display_code", "").upper() == codigo.upper():
                    pago = p
                    abono = db.session.execute(
                        db.select(Abono).filter_by(codigo=p.session_id)
                    ).scalar_one_or_none()
                    break

        if abono and pago is None:
            pago = db.session.execute(
                db.select(Payment).filter_by(session_id=abono.codigo)
            ).scalar_one_or_none()

        display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""
        return abono, pago, display_code

    def get_pedido_with_payment(self, codigo: str) -> tuple:
        """Return ``(Pedido, Payment)`` for the order identified by *codigo*.

        Returns ``(None, None)`` when the Pedido does not exist.
        The Payment may be ``None`` if the order has not been submitted for
        payment yet.
        """
        pedido = db.session.execute(
            db.select(Pedido).filter_by(codigo=codigo)
        ).scalar_one_or_none()
        if pedido is None:
            return None, None
        pago = (
            db.session.execute(
                db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
            ).scalar_one_or_none()
            if pedido.codigo_merchants
            else None
        )
        return pedido, pago

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def approve_abono(self, abono: Abono, pago: Payment) -> bool:
        """Mark *pago* as succeeded and credit *abono* amount to the apoderado.

        Returns ``True`` when the operation was performed, ``False`` when
        *pago* is not in ``"processing"`` state (already approved or not
        pending).
        """
        if pago.state != "processing":
            return False
        pago.state = "succeeded"
        saldo_actual = abono.apoderado.saldo_cuenta or 0
        abono.apoderado.saldo_cuenta = saldo_actual + int(abono.monto)
        db.session.commit()
        return True

    def approve_pedido(self, pedido: Pedido, pago: Payment) -> bool:
        """Mark *pago* as succeeded and set *pedido* to paid.

        Returns ``True`` when the operation was performed, ``False`` when
        *pago* is not in ``"processing"`` state.
        """
        from datetime import datetime

        if pago.state != "processing":
            return False
        pago.state = "succeeded"
        pedido.pagado = True
        pedido.estado = EstadoPedido.PAGADO
        pedido.fecha_pago = datetime.now()
        db.session.commit()
        return True
