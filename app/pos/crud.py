"""PosController — CRUD and business logic for the POS module.

Route functions in routes.py are thin HTTP wrappers that parse the request,
delegate to this controller, and return a Flask response.  The controller
uses only SQLAlchemy (via ``db``) and plain Python — no ``request``,
``current_user``, or ``url_for`` calls — making every method independently
testable.
"""

from datetime import date, datetime
from typing import Optional

from ..database import db
from ..model import Abono, Alumno, EstadoAlmuerzo, EstadoPedido, MenuDiario, OrdenCasino, Payment, Pedido


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

    def get_alumnos_activos(self) -> list[Alumno]:
        """Return all active Alumno records ordered by course and name."""
        return (
            db.session.execute(
                db.select(Alumno).filter_by(activo=True).order_by(Alumno.curso, Alumno.nombre)
            )
            .scalars()
            .all()
        )

    def get_alumnos_con_almuerzo_pendiente(self, fecha: Optional[date] = None) -> list[Alumno]:
        """Return active Alumno records that have a PENDIENTE OrdenCasino for *fecha* (default: today)."""
        if fecha is None:
            fecha = date.today()
        return (
            db.session.execute(
                db.select(Alumno)
                .join(OrdenCasino, OrdenCasino.alumno_id == Alumno.id)
                .where(
                    OrdenCasino.fecha == fecha,
                    OrdenCasino.estado == EstadoAlmuerzo.PENDIENTE,
                    Alumno.activo == True,  # noqa: E712
                )
                .order_by(Alumno.curso, Alumno.nombre)
            )
            .scalars()
            .all()
        )

    def get_alumno_by_tag(self, serial: str) -> Optional[Alumno]:
        """Return the Alumno matching *serial* (stored lowercase), or ``None``."""
        return db.session.execute(
            db.select(Alumno).filter_by(tag=serial.lower())
        ).scalar_one_or_none()

    def get_alumno_con_orden(self, serial: str, fecha: Optional[date] = None) -> dict:
        """Return a full canteen scan result for *serial*.

        Returns a dict with keys:
        - ``alumno``: the Alumno ORM object or ``None`` when tag not found
        - ``orden``: pending OrdenCasino for *fecha* (defaults to today), or ``None``
        - ``ya_entregado``: True if the alumno already received a lunch today
        """
        if fecha is None:
            fecha = date.today()
        alumno = self.get_alumno_by_tag(serial)
        orden = None
        ya_entregado = False
        if alumno:
            orden = db.session.execute(
                db.select(OrdenCasino).filter_by(
                    alumno_id=alumno.id,
                    fecha=fecha,
                    estado=EstadoAlmuerzo.PENDIENTE,
                )
            ).scalar_one_or_none()
            entregado = db.session.execute(
                db.select(OrdenCasino).filter_by(
                    alumno_id=alumno.id,
                    fecha=fecha,
                    estado=EstadoAlmuerzo.ENTREGADO,
                )
            ).scalar_one_or_none()
            ya_entregado = entregado is not None
        return {"alumno": alumno, "orden": orden, "ya_entregado": ya_entregado}

    def get_ordenes_entregadas_hoy(self, limit: int = 20) -> list[OrdenCasino]:
        """Return the most recent delivered OrdenCasino records for today."""
        today = date.today()
        return (
            db.session.execute(
                db.select(OrdenCasino)
                .filter_by(fecha=today, estado=EstadoAlmuerzo.ENTREGADO)
                .order_by(OrdenCasino.fecha_entrega.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_menus_hoy(self) -> list[MenuDiario]:
        """Return today's active MenuDiario entries available for sale."""
        today = date.today()
        from sqlalchemy import or_
        return (
            db.session.execute(
                db.select(MenuDiario)
                .where(
                    MenuDiario.activo == True,  # noqa: E712
                    MenuDiario.fuera_stock == False,  # noqa: E712
                    or_(MenuDiario.dia == today, MenuDiario.es_permanente == True),  # noqa: E712
                )
                .order_by(MenuDiario.dia)
            )
            .scalars()
            .all()
        )

    def buscar_alumnos(self, query: str) -> list[Alumno]:
        """Search active alumnos by name or course (case-insensitive prefix match)."""
        q = f"%{query.lower()}%"
        from sqlalchemy import func, or_
        return (
            db.session.execute(
                db.select(Alumno)
                .where(
                    Alumno.activo == True,  # noqa: E712
                    or_(
                        func.lower(Alumno.nombre).like(q),
                        func.lower(Alumno.curso).like(q),
                    ),
                )
                .order_by(Alumno.curso, Alumno.nombre)
                .limit(20)
            )
            .scalars()
            .all()
        )

    def get_alumno_con_orden_by_id(self, alumno_id: int, fecha: Optional[date] = None) -> dict:
        """Same as ``get_alumno_con_orden`` but looks up by alumno primary key.

        Returns a dict with the same keys as :meth:`get_alumno_con_orden`.
        """
        if fecha is None:
            fecha = date.today()
        alumno = db.session.get(Alumno, alumno_id)
        if alumno is None:
            return {"alumno": None, "orden": None, "ya_entregado": False}
        orden = db.session.execute(
            db.select(OrdenCasino).filter_by(
                alumno_id=alumno_id,
                fecha=fecha,
                estado=EstadoAlmuerzo.PENDIENTE,
            )
        ).scalar_one_or_none()
        ya_entregado = db.session.execute(
            db.select(OrdenCasino).filter_by(
                alumno_id=alumno_id,
                fecha=fecha,
                estado=EstadoAlmuerzo.ENTREGADO,
            )
        ).scalar_one_or_none() is not None
        return {"alumno": alumno, "orden": orden, "ya_entregado": ya_entregado}

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

    def entregar_almuerzo(self, orden_id: int) -> Optional[OrdenCasino]:
        """Mark an OrdenCasino as ENTREGADO (lunch delivered).

        Returns the updated OrdenCasino, or ``None`` when not found or already
        not in PENDIENTE state.
        """
        orden = db.session.get(OrdenCasino, orden_id)
        if not orden or orden.estado != EstadoAlmuerzo.PENDIENTE:
            return None
        orden.estado = EstadoAlmuerzo.ENTREGADO
        orden.fecha_entrega = datetime.now()
        db.session.commit()
        return orden

    def crear_orden_kiosko(self, alumno: Alumno, menu: MenuDiario, fecha: Optional[date] = None) -> OrdenCasino:
        """Create an OrdenCasino for a kiosk (cash) sale, immediately marked ENTREGADO.

        This is used when a child arrives at the kiosk without a pre-paid lunch.
        The staff selects the alumno and today's menu; the order is created and
        immediately marked as delivered so the child can join the queue.

        A Pedido record is created first so that ``pedido_codigo`` always
        references a real Pedido (required by the data model).
        """
        if fecha is None:
            fecha = date.today()

        # Create the backing Pedido so pedido_codigo is a real order reference
        pedido = Pedido()
        pedido.extra_attrs = [{"slug": menu.slug, "date": fecha.isoformat(), "note": "kiosko", "alumnos": [{"id": alumno.id}]}]
        pedido.precio_total = menu.precio or 0
        pedido.pagado = True
        pedido.estado = EstadoPedido.PAGADO
        pedido.fecha_pago = datetime.now()
        db.session.add(pedido)
        db.session.flush()  # obtain pedido.codigo without committing yet

        orden = OrdenCasino()
        orden.pedido_codigo = pedido.codigo
        orden.alumno_id = alumno.id
        orden.menu_slug = menu.slug
        orden.menu_descripcion = menu.descripcion
        orden.menu_precio = menu.precio
        orden.fecha = fecha
        orden.estado = EstadoAlmuerzo.ENTREGADO
        orden.fecha_entrega = datetime.now()
        db.session.add(orden)
        db.session.commit()
        return orden

    def get_dashboard_stats(self) -> dict:
        """Return today's summary statistics for the POS dashboard.

        Returns a dict with keys:
        - ``ordenes_pendientes_hoy``: OrdenCasino count with PENDIENTE estado for today
        - ``ordenes_entregadas_hoy``: OrdenCasino count with ENTREGADO estado for today
        - ``total_alumnos``: total active Alumno count
        - ``alumnos_con_tag``: active Alumno count that have a tag assigned
        """
        from sqlalchemy import func

        today = date.today()
        ordenes_pendientes = db.session.execute(
            db.select(func.count()).select_from(OrdenCasino).where(
                OrdenCasino.fecha == today,
                OrdenCasino.estado == EstadoAlmuerzo.PENDIENTE,
            )
        ).scalar() or 0

        ordenes_entregadas = db.session.execute(
            db.select(func.count()).select_from(OrdenCasino).where(
                OrdenCasino.fecha == today,
                OrdenCasino.estado == EstadoAlmuerzo.ENTREGADO,
            )
        ).scalar() or 0

        total_alumnos = db.session.execute(
            db.select(func.count()).select_from(Alumno).where(Alumno.activo == True)  # noqa: E712
        ).scalar() or 0

        alumnos_con_tag = db.session.execute(
            db.select(func.count()).select_from(Alumno).where(
                Alumno.activo == True,  # noqa: E712
                Alumno.tag.isnot(None),
            )
        ).scalar() or 0

        return {
            "ordenes_pendientes_hoy": ordenes_pendientes,
            "ordenes_entregadas_hoy": ordenes_entregadas,
            "total_alumnos": total_alumnos,
            "alumnos_con_tag": alumnos_con_tag,
            "porcentaje_cobertura_nfc": int(alumnos_con_tag / total_alumnos * 100) if total_alumnos else 0,
        }

    def canjear_con_credito(self, alumno: Alumno, menu: MenuDiario, fecha: Optional[date] = None) -> Optional[OrdenCasino]:
        """Create an OrdenCasino using the apoderado's credit balance (canje directo).

        This is used at the POS Casino when a student has no reservation but
        the apoderado has enough credit to cover the menu price.  The menu
        price is deducted from ``alumno.apoderado.saldo_cuenta`` and the order
        is immediately marked as ENTREGADO.

        Returns the new OrdenCasino, or ``None`` if there is insufficient
        credit or the menu has no price.
        """
        if fecha is None:
            fecha = date.today()

        precio = int(menu.precio or 0)
        saldo_actual = alumno.apoderado.saldo_cuenta or 0
        if precio <= 0 or saldo_actual < precio:
            return None

        # Create the backing Pedido so pedido_codigo references a real order
        pedido = Pedido()
        pedido.extra_attrs = [{"slug": menu.slug, "date": fecha.isoformat(), "note": "canje_credito", "alumnos": [{"id": alumno.id}]}]
        pedido.precio_total = precio
        pedido.pagado = True
        pedido.estado = EstadoPedido.PAGADO
        pedido.fecha_pago = datetime.now()
        pedido.apoderado_id = alumno.apoderado.id
        db.session.add(pedido)
        db.session.flush()

        orden = OrdenCasino()
        orden.pedido_codigo = pedido.codigo
        orden.alumno_id = alumno.id
        orden.menu_slug = menu.slug
        orden.menu_descripcion = menu.descripcion
        orden.menu_precio = menu.precio
        orden.fecha = fecha
        orden.estado = EstadoAlmuerzo.ENTREGADO
        orden.fecha_entrega = datetime.now()
        db.session.add(orden)

        alumno.apoderado.saldo_cuenta = saldo_actual - precio
        db.session.commit()
        return orden

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
        if pago.state != "processing":
            return False
        pago.state = "succeeded"
        pedido.pagado = True
        pedido.estado = EstadoPedido.PAGADO
        pedido.fecha_pago = datetime.now()
        db.session.commit()
        return True
