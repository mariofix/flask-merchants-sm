"""SchoolStaffController - all CRUD and business logic for the staff module.

Routes in route.py are thin HTTP wrappers; they parse the request, delegate to
this controller, then return a Flask response.  The controller uses only
SQLAlchemy (via ``db``) and plain Python - no ``request``, ``current_user``, or
``url_for`` calls.  This makes every method independently testable.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func

from ..database import db
from ..model import (
    EstadoPedido,
    MenuDiario,
    Payment,
    SchoolStaff,
    SchoolStaffPedido,
)


class SchoolStaffController:
    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_staff(self, user) -> Optional[SchoolStaff]:
        """Return the SchoolStaff profile linked to *user*, or ``None``."""
        return db.session.execute(
            db.select(SchoolStaff).filter_by(usuario=user)
        ).scalar_one_or_none()

    def get_deuda_actual(self, staff: SchoolStaff) -> Decimal:
        """Return the total unpaid amount for *staff*."""
        result = db.session.execute(
            db.select(func.coalesce(func.sum(SchoolStaffPedido.precio_total), 0)).where(
                and_(
                    SchoolStaffPedido.staff_id == staff.id,
                    SchoolStaffPedido.pagado == False,  # noqa: E712
                    SchoolStaffPedido.estado != EstadoPedido.CANCELADA,
                )
            )
        ).scalar()
        return Decimal(result or 0)

    def get_deuda_mes_actual(self, staff: SchoolStaff) -> Decimal:
        """Return the total unpaid amount for *staff* in the current month."""
        today = date.today()
        inicio_mes = today.replace(day=1)
        result = db.session.execute(
            db.select(func.coalesce(func.sum(SchoolStaffPedido.precio_total), 0)).where(
                and_(
                    SchoolStaffPedido.staff_id == staff.id,
                    SchoolStaffPedido.pagado == False,  # noqa: E712
                    SchoolStaffPedido.estado != EstadoPedido.CANCELADA,
                    SchoolStaffPedido.fecha_pedido >= inicio_mes,
                )
            )
        ).scalar()
        return Decimal(result or 0)

    def get_pedidos(self, staff: SchoolStaff, limit: int = 30) -> list[dict]:
        """Return the last *limit* pedidos enriched with payment info."""
        pedidos = db.session.execute(
            db.select(SchoolStaffPedido)
            .filter_by(staff_id=staff.id)
            .order_by(SchoolStaffPedido.fecha_pedido.desc())
            .limit(limit)
        ).scalars().all()

        result = []
        for pedido in pedidos:
            pago = None
            if pedido.codigo_merchants:
                pago = db.session.execute(
                    db.select(Payment).filter_by(merchants_id=pedido.codigo_merchants)
                ).scalar_one_or_none()
            result.append({"pedido": pedido, "pago": pago})
        return result

    def puede_comprar(self, staff: SchoolStaff, monto: Decimal) -> bool:
        """Return True if *staff* can add *monto* to their post-pay tab.

        Returns ``False`` when ``limite_cuenta`` is ``None`` (not configured)
        or ``0`` (no credit available).
        """
        if not staff.limite_cuenta or staff.limite_cuenta <= 0:
            return False
        deuda_actual = self.get_deuda_actual(staff)
        return (deuda_actual + monto) <= Decimal(staff.limite_cuenta)

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def create_staff(self, nombre: str, user, limite_cuenta: Optional[int] = None) -> SchoolStaff:
        """Create and persist a new SchoolStaff record linked to *user*."""
        staff = SchoolStaff()
        staff.nombre = nombre
        staff.usuario_id = user.id
        staff.limite_cuenta = limite_cuenta
        db.session.add(staff)
        db.session.commit()
        return staff

    def update_ajustes(self, staff: SchoolStaff, user, data: dict) -> None:
        """Persist changes from the /ajustes form for *staff* and *user*."""
        staff.nombre = data.get("nombre", staff.nombre)
        staff.informe_semanal = bool(data.get("informe_semanal"))
        if data.get("phone"):
            user.username = data["phone"]
        db.session.commit()

    def crea_pedido(self, payload: list, staff_id: int) -> str:
        """Create a new SchoolStaffPedido from *payload* and return its codigo."""
        pedido = SchoolStaffPedido()
        pedido.extra_attrs = payload
        pedido.precio_total = Decimal(0)
        pedido.staff_id = staff_id
        db.session.add(pedido)
        db.session.commit()
        return pedido.codigo

    def process_payment_completion(self, pedido: SchoolStaffPedido) -> None:
        """Mark *pedido* as paid and dispatch confirmation email."""
        from ..tasks import send_confirmacion_staff_pedido_pagado

        pedido.estado = EstadoPedido.PAGADO
        pedido.pagado = True
        pedido.fecha_pago = datetime.now()
        db.session.commit()

        send_confirmacion_staff_pedido_pagado.delay({
            "staff_id": pedido.staff_id,
            "pedido_codigo": pedido.codigo,
            "total": int(pedido.precio_total),
        })
