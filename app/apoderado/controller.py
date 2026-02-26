"""ApoderadoController — all CRUD and business logic for the apoderado module.

Routes in route.py are thin HTTP wrappers; they parse the request, delegate to
this controller, then return a Flask response.  The controller uses only
SQLAlchemy (via ``db``) and plain Python — no ``request``, ``current_user``, or
``url_for`` calls.  This makes every method independently testable.
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from slugify import slugify
from sqlalchemy import and_, func

from ..database import db
from ..model import (
    Abono,
    Alumno,
    Apoderado,
    EstadoAlmuerzo,
    EstadoPedido,
    MenuDiario,
    OrdenCasino,
    Payment,
    Pedido,
)


class ApoderadoController:
    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_apoderado(self, user) -> Optional[Apoderado]:
        """Return the Apoderado profile linked to *user*, or ``None``."""
        return db.session.execute(
            db.select(Apoderado).filter_by(usuario=user)
        ).scalar_one_or_none()

    def get_spending_stats(self, apoderado: Apoderado) -> dict:
        """Return ``{alumno_id: {gasto_hoy, gasto_semana}}`` for all alumnos."""
        today = date.today()
        seven_days_ago = today - timedelta(days=6)
        stats: dict[int, dict] = {}
        for alumno in apoderado.alumnos:
            gasto_hoy = db.session.execute(
                db.select(func.coalesce(func.sum(OrdenCasino.menu_precio), 0)).where(
                    and_(
                        OrdenCasino.alumno_id == alumno.id,
                        OrdenCasino.fecha == today,
                        OrdenCasino.estado != EstadoAlmuerzo.CANCELADO,
                    )
                )
            ).scalar() or Decimal(0)
            gasto_semana = db.session.execute(
                db.select(func.coalesce(func.sum(OrdenCasino.menu_precio), 0)).where(
                    and_(
                        OrdenCasino.alumno_id == alumno.id,
                        OrdenCasino.fecha >= seven_days_ago,
                        OrdenCasino.fecha <= today,
                        OrdenCasino.estado != EstadoAlmuerzo.CANCELADO,
                    )
                )
            ).scalar() or Decimal(0)
            stats[alumno.id] = {
                "gasto_hoy": int(gasto_hoy),
                "gasto_semana": int(gasto_semana),
            }
        return stats

    def get_alumno_spending(self, alumno: Alumno) -> dict:
        """Return spending totals for *alumno* over 1, 7 and 14 days."""
        today = date.today()

        def _sum(desde: date) -> int:
            result = db.session.execute(
                db.select(func.coalesce(func.sum(OrdenCasino.menu_precio), 0)).where(
                    and_(
                        OrdenCasino.alumno_id == alumno.id,
                        OrdenCasino.fecha >= desde,
                        OrdenCasino.fecha <= today,
                        OrdenCasino.estado != EstadoAlmuerzo.CANCELADO,
                    )
                )
            ).scalar()
            return int(result or 0)

        return {
            "uso_24h": _sum(today),
            "uso_7d": _sum(today - timedelta(days=6)),
            "uso_14d": _sum(today - timedelta(days=13)),
        }

    def get_pedidos_for_apoderado(self, apoderado: Apoderado) -> list[dict]:
        """Return the last 30 pedidos (direct + legacy) enriched with payment info."""
        pedidos_directos = (
            db.session.execute(
                db.select(Pedido)
                .filter_by(apoderado_id=apoderado.id)
                .order_by(Pedido.fecha_pedido.desc())
                .limit(30)
            )
            .scalars()
            .all()
        )

        alumno_ids = [a.id for a in apoderado.alumnos]
        codigos_directos = {p.codigo for p in pedidos_directos}
        pedidos_legacy = []
        if alumno_ids:
            codigos_ordenes = (
                db.session.execute(
                    db.select(OrdenCasino.pedido_codigo)
                    .where(OrdenCasino.alumno_id.in_(alumno_ids))
                    .distinct()
                )
                .scalars()
                .all()
            )
            codigos_legacy = [c for c in codigos_ordenes if c not in codigos_directos]
            if codigos_legacy:
                pedidos_legacy = (
                    db.session.execute(
                        db.select(Pedido).where(Pedido.codigo.in_(codigos_legacy))
                    )
                    .scalars()
                    .all()
                )

        todos = sorted(
            list(pedidos_directos) + list(pedidos_legacy),
            key=lambda p: p.fecha_pedido,
            reverse=True,
        )[:30]

        result = []
        for pedido in todos:
            pago = None
            if pedido.codigo_merchants:
                pago = db.session.execute(
                    db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
                ).scalar_one_or_none()
            ordenes = (
                db.session.execute(
                    db.select(OrdenCasino).filter_by(pedido_codigo=pedido.codigo)
                )
                .scalars()
                .all()
            )
            result.append({"pedido": pedido, "pago": pago, "ordenes": ordenes})
        return result

    def get_abonos_info(self, apoderado: Apoderado) -> list[dict]:
        """Return all abonos for *apoderado* paired with their Payment records."""
        abono_list = apoderado.abonos
        codigos = [a.codigo for a in abono_list]
        pagos_by_codigo = {}
        if codigos:
            pagos = (
                db.session.execute(
                    db.select(Payment).where(Payment.session_id.in_(codigos))
                )
                .scalars()
                .all()
            )
            pagos_by_codigo = {p.session_id: p for p in pagos}
        return [{"abono": a, "pago": pagos_by_codigo.get(a.codigo)} for a in abono_list]

    def get_abono(self, codigo: str) -> tuple:
        """Return ``(Abono, Payment, display_code)`` for *codigo*, or ``(None, None, '')``."""
        abono = db.session.execute(
            db.select(Abono).filter_by(codigo=codigo)
        ).scalar_one_or_none()
        pago = db.session.execute(
            db.select(Payment).filter_by(session_id=codigo)
        ).scalar_one_or_none()
        display_code = (
            (pago.metadata_json or {}).get("display_code", "") if pago else ""
        )
        return abono, pago, display_code

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def toggle_alumno_activo(
        self, alumno: Alumno, motivo: str = "Bloqueado por apoderado"
    ) -> Alumno:
        """Toggle the ``activo`` flag on *alumno*.

        When deactivating, ``motivo`` is stored on the record so the UI can
        display a reason badge.  When reactivating, ``motivo`` is cleared.
        """
        alumno.activo = not alumno.activo
        alumno.motivo = None if alumno.activo else motivo
        db.session.commit()
        return alumno

    def create_apoderado(self, nombre: str, alumnos_count: int, user) -> Apoderado:
        """Create and persist a new Apoderado record linked to *user*."""
        apoderado = Apoderado()
        apoderado.nombre = nombre
        apoderado.alumnos_registro = int(alumnos_count)
        apoderado.usuario_id = user.id
        db.session.add(apoderado)
        db.session.commit()
        return apoderado

    def create_alumnos(self, apoderado: Apoderado, alumnos_data: list[dict]) -> None:
        """Persist a list of Alumno records for *apoderado*.

        Each dict must have ``nombre``, ``curso``, ``edad`` and optionally
        ``restricciones`` (list of restriction dicts).
        """
        for data in alumnos_data:
            alumno = Alumno()
            alumno.slug = slugify(
                f"{apoderado.nombre} {data.get('nombre', '')} {data.get('edad', '')}"
            )
            alumno.nombre = data.get("nombre", "")
            alumno.curso = data.get("curso", "")
            alumno.apoderado = apoderado
            alumno.restricciones = data.get("restricciones", [])
            db.session.add(alumno)
        db.session.commit()

    def update_preferences(self, apoderado: Apoderado, data: dict) -> None:
        """Apply wizard step-3 preferences to *apoderado* and cascade limits to alumnos."""
        apoderado.comprobantes_transferencia = bool(
            data.get("notificacion_comprobante")
        )
        apoderado.notificacion_compra = bool(data.get("notificacion_compra"))
        apoderado.informe_semanal = bool(data.get("informe_semanal"))
        apoderado.tag_compartido = bool(data.get("tag_compartido"))
        apoderado.copia_notificaciones = data.get("correo_alternativo") or None
        apoderado.maximo_diario = int(data.get("monto_diario") or 0)
        apoderado.maximo_semanal = int(data.get("monto_semanal") or 0)
        apoderado.limite_notificacion = int(data.get("limite_notificaciones") or 1500)
        apoderado.saldo_cuenta = 0
        for alumno in apoderado.alumnos:
            alumno.maximo_diario = apoderado.maximo_diario
            alumno.maximo_semanal = apoderado.maximo_semanal
        db.session.commit()

    def create_abono(
        self, apoderado: Apoderado, monto: Decimal, forma_pago: str
    ) -> Abono:
        """Create and persist a new Abono record."""
        nuevo = Abono()
        nuevo.monto = monto
        nuevo.apoderado = apoderado
        nuevo.descripcion = "Abono Web"
        nuevo.forma_pago = forma_pago
        db.session.add(nuevo)
        db.session.commit()
        return nuevo

    def update_ajustes(self, apoderado: Optional[Apoderado], user, data: dict) -> None:
        """Persist changes from the /ajustes form for *apoderado* and *user*."""
        if apoderado:
            apoderado.nombre = data.get("nombre", apoderado.nombre)
            apoderado.comprobantes_transferencia = bool(
                data.get("comprobantes_transferencia")
            )
            apoderado.notificacion_compra = bool(data.get("notificacion_compra"))
            apoderado.informe_semanal = bool(data.get("informe_semanal"))
            apoderado.tag_compartido = bool(data.get("tag_compartido"))
            apoderado.copia_notificaciones = data.get(
                "copia_notificaciones", apoderado.copia_notificaciones
            )
            try:
                if data.get("maximo_diario"):
                    apoderado.maximo_diario = int(data["maximo_diario"])
            except ValueError:
                pass
            try:
                if data.get("maximo_semanal"):
                    apoderado.maximo_semanal = int(data["maximo_semanal"])
            except ValueError:
                pass
            try:
                if data.get("limite_notificacion"):
                    apoderado.limite_notificacion = int(data["limite_notificacion"])
            except ValueError:
                pass
        if data.get("phone"):
            user.username = data["phone"]
        db.session.commit()

    def add_restriccion_alumnos(self, alumnos: list, nombre: str, motivo: str) -> None:
        """Append a dietary restriction to each alumno in *alumnos*."""
        nueva = {"nombre": nombre, "motivo": motivo}
        for alumno in alumnos:
            restricciones = list(alumno.restricciones or [])
            restricciones.append(nueva)
            alumno.restricciones = restricciones
        db.session.commit()

    def delete_restriccion_alumno(self, alumno: Alumno, index: int) -> None:
        """Remove the restriction at *index* from *alumno*.restricciones."""
        restricciones = list(alumno.restricciones or [])
        if 0 <= index < len(restricciones):
            restricciones.pop(index)
            alumno.restricciones = restricciones
            db.session.commit()

    # ------------------------------------------------------------------
    # Order / payment helpers
    # ------------------------------------------------------------------

    def crea_orden(self, payload: list, apoderado_id: Optional[int] = None) -> str:
        """Create a new Pedido from *payload* and return its codigo."""
        orden = Pedido()
        orden.extra_attrs = payload
        orden.precio_total = Decimal(0)
        if apoderado_id is not None:
            orden.apoderado_id = apoderado_id
        db.session.add(orden)
        db.session.commit()
        return orden.codigo

    def compute_advertencias(self, menu, alumnos_item: list) -> list[dict]:
        """Return dietary-restriction warnings for *menu* × *alumnos_item*.

        Works on ORM ``MenuDiario`` objects as well as ``SimpleNamespace``
        stubs used for virtual menus (rezagados).  Returns an empty list when
        the menu has no ``opciones`` attribute.
        """
        advertencias: list[dict] = []
        if not hasattr(menu, "opciones"):
            return advertencias

        platos = [opcion.plato for opcion in menu.opciones]
        menu_contiene_alergenos = any(
            getattr(p, "contiene_alergenos", False) for p in platos
        )
        menu_es_vegano = any(getattr(p, "es_vegano", False) for p in platos)
        menu_es_vegetariano = any(getattr(p, "es_vegetariano", False) for p in platos)

        for alumno in alumnos_item:
            if not hasattr(alumno, "restricciones") or not alumno.restricciones:
                continue
            restricciones = alumno.restricciones
            if not isinstance(restricciones, list):
                continue

            alergias = []
            tiene_vegano = False
            tiene_vegetariano = False
            for r in restricciones:
                if not isinstance(r, dict):
                    continue
                nombre = r.get("nombre", "")
                if r.get("motivo") == "Alergia":
                    alergias.append(nombre)
                nl = nombre.lower()
                if "vegano" in nl or "vegan" in nl:
                    tiene_vegano = True
                if "vegetariano" in nl or "vegetarian" in nl:
                    tiene_vegetariano = True

            if menu_contiene_alergenos and alergias:
                advertencias.append(
                    {
                        "alumno": alumno.nombre,
                        "tipo": "warning",
                        "mensaje": (
                            f"{alumno.nombre} tiene alergias declaradas "
                            f"({', '.join(alergias)}) y este menú contiene alérgenos."
                        ),
                    }
                )
            if menu_es_vegano and tiene_vegano:
                advertencias.append(
                    {
                        "alumno": alumno.nombre,
                        "tipo": "info",
                        "mensaje": f"Este menú incluye un plato vegano (aplica a {alumno.nombre}).",
                    }
                )
            elif menu_es_vegetariano and tiene_vegetariano:
                advertencias.append(
                    {
                        "alumno": alumno.nombre,
                        "tipo": "info",
                        "mensaje": f"Este menú incluye una opción vegetariana (aplica a {alumno.nombre}).",
                    }
                )

        # Deduplicate while preserving order
        seen: set = set()
        result = []
        for adv in advertencias:
            key = (adv["alumno"], adv["tipo"], adv["mensaje"])
            if key not in seen:
                seen.add(key)
                result.append(adv)
        return result

    def compute_descuento_promocional(
        self, resumen: list, corte_promocional: dict
    ) -> dict:
        """Return the promotional discount for qualifying alumnos in *resumen*.

        ``corte_promocional`` is the value of the ``corte_promocional`` Settings
        row, expected to be ``{"curso": <int>, "descuento": <int>}``.  Any
        alumno whose course number (leading digits of ``alumno.curso``) is
        less than or equal to ``curso`` gets ``descuento`` subtracted from the
        price of each lunch they appear in.

        Returns ``{"descuento_total": Decimal, "alumnos": list[str]}``.
        """
        try:
            curso_max = int(corte_promocional.get("curso", 0))
            descuento_por_almuerzo = int(corte_promocional.get("descuento", 0))
        except (TypeError, ValueError):
            return {"descuento_total": Decimal(0), "alumnos": []}

        if not curso_max or not descuento_por_almuerzo:
            return {"descuento_total": Decimal(0), "alumnos": []}

        total_descuento = Decimal(0)
        seen_names: list[str] = []

        for item in resumen:
            for alumno in item.get("alumnos", []):
                if hasattr(alumno, "curso"):
                    curso_str = alumno.curso
                    nombre = alumno.nombre if hasattr(alumno, "nombre") else "—"
                elif isinstance(alumno, dict):
                    curso_str = alumno.get("curso")
                    nombre = alumno.get("nombre", "—")
                else:
                    continue

                if not curso_str:
                    continue

                m = re.match(r"(\d+)", str(curso_str))
                if m and int(m.group(1)) <= curso_max:
                    total_descuento += Decimal(descuento_por_almuerzo)
                    if nombre not in seen_names:
                        seen_names.append(nombre)

        return {"descuento_total": total_descuento, "alumnos": seen_names}

    def process_payment_completion(self, pedido: Pedido) -> None:
        """Create one OrdenCasino per item×alumno after a Pedido is paid.

        Idempotent: skips silently if OrdenCasino rows already exist for this
        pedido.  Dispatches send_confirmacion_orden_pagado after creating the
        orders when the Pedido has an associated Apoderado.
        """
        from datetime import date as _date
        from ..routes import get_casino_timelimits

        items = pedido.extra_attrs or []
        existing = db.session.execute(
            db.select(OrdenCasino).filter_by(pedido_codigo=pedido.codigo).limit(1)
        ).scalar_one_or_none()
        if existing:
            return

        email_items = []
        for item in items:
            fecha_str = item.get("date")
            slug = item.get("slug")
            nota = item.get("note") or None
            alumnos_list = item.get("alumnos", [])
            if not fecha_str or not slug:
                continue
            try:
                fecha = _date.fromisoformat(fecha_str)
            except ValueError:
                continue

            menu = db.session.execute(
                db.select(MenuDiario).filter_by(slug=slug)
            ).scalar_one_or_none()
            if menu is None:
                _, _, menu_rezagados_cfg = get_casino_timelimits()
                if slug == menu_rezagados_cfg["slug"]:
                    from types import SimpleNamespace

                    menu = SimpleNamespace(
                        slug=menu_rezagados_cfg["slug"],
                        descripcion=menu_rezagados_cfg["descripcion"],
                        precio=menu_rezagados_cfg["precio"],
                    )
                else:
                    from flask_merchants import merchants_audit

                    merchants_audit.warning(
                        "ordencasino_menu_not_found: pedido=%s slug=%r date=%r",
                        pedido.codigo,
                        slug,
                        fecha_str,
                    )

            alumno_names = []
            for alumno_data in alumnos_list:
                try:
                    alumno_id = int(alumno_data.get("id"))
                except (TypeError, ValueError):
                    continue
                alumno = db.session.get(Alumno, alumno_id)
                if not alumno:
                    continue
                orden = OrdenCasino()
                orden.pedido_codigo = pedido.codigo
                orden.alumno_id = alumno_id
                orden.menu_slug = slug
                orden.menu_descripcion = menu.descripcion if menu else None
                orden.menu_precio = menu.precio if menu else None
                orden.fecha = fecha
                orden.nota = nota
                db.session.add(orden)
                alumno_names.append(alumno.nombre)

            if alumno_names:
                email_items.append(
                    {
                        "fecha": fecha_str,
                        "descripcion": menu.descripcion if menu else slug,
                        "alumnos_str": ", ".join(alumno_names),
                        "precio": (
                            int(menu.precio) * len(alumno_names)
                            if menu and menu.precio
                            else 0
                        ),
                        "nota": nota or "",
                    }
                )

        db.session.commit()

        if pedido.apoderado_id and email_items:
            from ..tasks import send_confirmacion_orden_pagado

            send_confirmacion_orden_pagado.delay(
                {
                    "apoderado_id": pedido.apoderado_id,
                    "pedido_codigo": pedido.codigo,
                    "total": int(pedido.precio_total),
                    "items": email_items,
                }
            )
