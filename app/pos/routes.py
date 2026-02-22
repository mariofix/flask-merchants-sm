from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, url_for, redirect
from flask_security import current_user

from ..database import db
from ..extensions import flask_merchants
from ..model import Apoderado, EstadoPedido, Pedido, Abono, Payment, MenuDiario, Alumno

from datetime import datetime

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/", methods=["GET"])
def index():
    alumnos_sin_tag = (
        db.session.execute(db.select(Alumno).filter_by(tag=None).order_by(Alumno.curso, Alumno.slug)).scalars().all()
    )

    return render_template("pos/dashboard.html", alumnos_sin_tag=alumnos_sin_tag)


def creaOrden(payload, apoderado_id=None):
    orden = Pedido()
    orden.extra_attrs = payload
    orden.precio_total = Decimal(0)
    if apoderado_id is not None:
        orden.apoderado_id = apoderado_id
    db.session.add(orden)
    db.session.commit()

    return orden.codigo


@pos_bp.route("/orden-web", methods=["POST"])
def ordenweb():
    payload = request.get_json(force=True)
    ordenes = payload["purchases"]

    apoderado_id = None
    if current_user.is_authenticated:
        apoderado = db.session.execute(
            db.select(Apoderado).filter_by(usuario=current_user)
        ).scalar_one_or_none()
        if apoderado:
            apoderado_id = apoderado.id

    nueva_orden = creaOrden(ordenes, apoderado_id=apoderado_id)

    return jsonify(
        {
            "status": "OK",
            "redirect_url": url_for("pos.pago_orden", orden=nueva_orden),
        }
    )


@pos_bp.route("/valida_tag/<string:serial>", methods=["GET"])
def valida_tag(serial: str):
    alumno = db.session.execute(db.select(Alumno).filter_by(tag=serial.upper())).scalar_one_or_none()

    if not alumno:
        return jsonify({"error": "TAG no encontrado en el sistema", "serial": serial}), 404

    return (
        jsonify({"valid": True, "mensaje": f"TAG Asignado: Alumno {alumno.id}", "serial": serial}),
        200,
    )


@pos_bp.route("/pago-orden/<orden>", methods=["GET", "POST"])
def pago_orden(orden):
    pedido = db.session.execute(db.select(Pedido).filter_by(codigo=orden)).scalar_one_or_none()
    resumen = []
    pago = None
    display_code = ""
    total = Decimal(0)

    apoderado = None
    if current_user.is_authenticated:
        apoderado = db.session.execute(
            db.select(Apoderado).filter_by(usuario=current_user)
        ).scalar_one_or_none()

    if pedido:
        # Collect all alumno IDs up-front to avoid N+1 queries
        all_alumno_ids = [
            int(a["id"])
            for item in pedido.extra_attrs
            for a in item.get("alumnos", [])
        ]
        alumnos_by_id = {}
        if all_alumno_ids:
            alumnos_by_id = {
                a.id: a
                for a in db.session.execute(
                    db.select(Alumno).filter(Alumno.id.in_(all_alumno_ids))
                ).scalars().all()
            }

        from ..routes import get_casino_timelimits
        _, _, menu_rezagados_cfg = get_casino_timelimits()

        for item in pedido.extra_attrs:
            menu = db.session.execute(db.select(MenuDiario).filter_by(slug=item["slug"])).scalar_one_or_none()
            if menu is None and item["slug"] == menu_rezagados_cfg["slug"]:
                from types import SimpleNamespace
                menu = SimpleNamespace(
                    slug=menu_rezagados_cfg["slug"],
                    descripcion=menu_rezagados_cfg["descripcion"],
                    precio=menu_rezagados_cfg["precio"],
                )
            alumnos_item = [
                alumnos_by_id.get(int(a["id"]), {"nombre": a.get("nombre", "—"), "curso": None})
                for a in item.get("alumnos", [])
            ]
            resumen.append(
                {
                    "fecha": item["date"],
                    "menu": item["slug"],
                    "nota": item["note"],
                    "detalle_menu": menu,
                    "alumnos": alumnos_item,
                    "advertencias": _compute_advertencias(menu, alumnos_item),
                }
            )
        total = sum(
            item["detalle_menu"].precio * len(item["alumnos"])
            for item in resumen
            if item["detalle_menu"] is not None
        )

        if request.method == "POST":
            forma_pago = request.form.get("forma-de-pago", "cafeteria")

            # Resolve saldo_cuenta discount
            descuento_saldo = Decimal(0)
            if apoderado and apoderado.saldo_cuenta and apoderado.saldo_cuenta >= 50:
                try:
                    raw = int(request.form.get("descuento_saldo", 0))
                    max_descuento = min(apoderado.saldo_cuenta, int(total))
                    raw = max(0, min(raw, max_descuento))
                    descuento_saldo = Decimal(raw)
                except (ValueError, TypeError):
                    descuento_saldo = Decimal(0)

            monto_a_pagar = total - descuento_saldo

            if monto_a_pagar <= 0:
                # Fully covered by saldo – complete the pedido without a payment provider
                if descuento_saldo > 0:
                    apoderado.saldo_cuenta = (apoderado.saldo_cuenta or 0) - int(descuento_saldo)
                pedido.precio_total = total
                pedido.estado = EstadoPedido.PAGADO
                pedido.pagado = True
                pedido.fecha_pago = datetime.now()
                db.session.commit()
                _process_payment_completion(pedido)
                return redirect(url_for("pos.pago_orden", orden=pedido.codigo))

            session = flask_merchants.get_client(forma_pago).payments.create_checkout(
                amount=monto_a_pagar,
                currency="CLP",
                success_url=url_for("pos.pago_orden", orden=pedido.codigo, _external=True),
                cancel_url=url_for("pos.pago_orden", orden=pedido.codigo, _external=True),
                metadata={"pedido_codigo": pedido.codigo},
            )
            # Deduct saldo only after the provider session is created successfully
            if descuento_saldo > 0:
                apoderado.saldo_cuenta = (apoderado.saldo_cuenta or 0) - int(descuento_saldo)
            flask_merchants.save_session(
                session,
                model_class=Payment,
                request_payload={
                    "pedido_codigo": pedido.codigo,
                    "monto": str(monto_a_pagar),
                    "currency": "CLP",
                    "forma_pago": forma_pago,
                    "descuento_saldo": str(descuento_saldo),
                },
            )
            pedido.codigo_merchants = session.session_id
            pedido.precio_total = total
            pedido.estado = EstadoPedido.PENDIENTE
            if forma_pago == "cafeteria":
                flask_merchants.update_state(session.session_id, "processing")
            db.session.commit()

            # Enqueue apoderado notification (no admin copy)
            from ..tasks import send_notificacion_pedido_pendiente
            pedido_url = url_for("pos.pago_orden", orden=pedido.codigo, _external=True)
            send_notificacion_pedido_pendiente.delay({
                "pedido_codigo": pedido.codigo,
                "session_id": session.session_id,
                "forma_pago": forma_pago,
                "total": int(total),
                "redirect_url": session.redirect_url if forma_pago != "cafeteria" else "",
                "pedido_url": pedido_url,
                "items": [
                    {
                        "descripcion": item["detalle_menu"].descripcion if item.get("detalle_menu") else item["menu"],
                        "fecha": item["fecha"],
                        "nota": item.get("nota", ""),
                        "precio": int(item["detalle_menu"].precio) if item.get("detalle_menu") else 0,
                        "alumnos_str": ", ".join(
                            a.nombre if hasattr(a, "nombre") else a.get("nombre", "")
                            for a in item.get("alumnos", [])
                        ),
                        "alumnos": [
                            {"id": a.id if hasattr(a, "id") else a.get("id")}
                            for a in item.get("alumnos", [])
                        ],
                    }
                    for item in resumen
                ],
            })

            if forma_pago != "cafeteria" and session.redirect_url:
                return redirect(session.redirect_url)
            return redirect(url_for("pos.pago_orden", orden=pedido.codigo))

        if pedido.codigo_merchants:
            pago = db.session.execute(
                db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
            ).scalar_one_or_none()
            display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""

    return render_template(
        "pos/venta-web.html",
        pedido=resumen,
        orden=pedido,
        total=total,
        pago=pago,
        display_code=display_code,
        apoderado=apoderado,
    )


@pos_bp.route("/venta", methods=["POST"])
def venta():
    return render_template("pos/venta.html")


@pos_bp.route("/buscar-abono", methods=["GET", "POST"])
def buscar_abono():
    from flask_security import current_user
    if not (current_user.is_authenticated and (current_user.has_role("admin") or current_user.has_role("pos"))):
        from flask import abort
        abort(403)

    abono = None
    pago = None
    display_code = ""
    codigo_buscado = ""

    if request.method == "POST":
        codigo_buscado = request.form.get("codigo", "").strip()
        if codigo_buscado:
            # Try to find by Abono.codigo (UUID) first
            abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo_buscado)).scalar_one_or_none()
            if not abono:
                # Try to find Payment by display_code in metadata_json
                pagos = db.session.execute(db.select(Payment)).scalars().all()
                for p in pagos:
                    if (p.metadata_json or {}).get("display_code", "").upper() == codigo_buscado.upper():
                        pago = p
                        abono = db.session.execute(
                            db.select(Abono).filter_by(codigo=p.session_id)
                        ).scalar_one_or_none()
                        break

        if abono:
            pago = pago or db.session.execute(
                db.select(Payment).filter_by(session_id=abono.codigo)
            ).scalar_one_or_none()
            display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""

    return render_template(
        "pos/buscar-abono.html",
        abono=abono,
        pago=pago,
        display_code=display_code,
        codigo_buscado=codigo_buscado,
    )


@pos_bp.route("/api/abono/<string:codigo>", methods=["GET"])
def api_buscar_abono(codigo):
    from flask_security import current_user
    if not (current_user.is_authenticated and (current_user.has_role("admin") or current_user.has_role("pos"))):
        return jsonify({"error": "No autorizado"}), 403

    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    if not abono:
        # Search by display_code
        pagos = db.session.execute(db.select(Payment)).scalars().all()
        for p in pagos:
            if (p.metadata_json or {}).get("display_code", "").upper() == codigo.upper():
                abono = db.session.execute(
                    db.select(Abono).filter_by(codigo=p.session_id)
                ).scalar_one_or_none()
                break

    if not abono:
        return jsonify({"error": "Abono no encontrado", "codigo": codigo}), 404

    pago = db.session.execute(db.select(Payment).filter_by(session_id=abono.codigo)).scalar_one_or_none()
    display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""
    return jsonify({
        "found": True,
        "abono": abono.to_dict(),
        "pago_estado": pago.state if pago else None,
        "display_code": display_code,
        "detalle_url": url_for("apoderado_cliente.abono_detalle", codigo=abono.codigo),
        "completa_url": url_for("pos.completa_abono", codigo=abono.codigo) if (pago and pago.state == "processing") else None,
    })


@pos_bp.route("/abono-web", methods=["GET", "POST"])
def abono():
    return render_template("pos/abono.html")


@pos_bp.route("/casino", methods=["GET"])
def casino():
    return render_template("pos/casino.html")


@pos_bp.route("/completa-abono/<string:codigo>")
def completa_abono(codigo):
    from flask_security import current_user, roles_accepted
    from ..tasks import send_comprobante_abono, send_notificacion_admin_abono, send_copia_notificaciones_abono

    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = db.session.execute(db.select(Payment).filter_by(session_id=codigo)).scalar_one_or_none()

    if (
        abono
        and pago
        and pago.state == "processing"
        and (current_user.has_role("admin") or current_user.has_role("pos"))
    ):
        pago.state = "succeeded"
        saldo_actual = abono.apoderado.saldo_cuenta or 0
        nuevo_saldo = saldo_actual + int(abono.monto)
        abono.apoderado.saldo_cuenta = nuevo_saldo
        db.session.commit()

        from flask_merchants import merchants_audit
        merchants_audit.info(
            "abono_aprobado: codigo=%s apoderado_id=%s email=%r monto=%s nuevo_saldo=%s",
            abono.codigo,
            abono.apoderado.id,
            abono.apoderado.usuario.email,
            int(abono.monto),
            nuevo_saldo,
        )

        abono_info = {
            "id": abono.id,
            "codigo": abono.codigo,
            "monto": int(abono.monto),
            "forma_pago": abono.forma_pago,
            "descripcion": abono.descripcion,
            "apoderado_nombre": abono.apoderado.nombre,
            "apoderado_email": abono.apoderado.usuario.email,
            "saldo_cuenta": nuevo_saldo,
            "copia_notificaciones": abono.apoderado.copia_notificaciones,
        }
        # Admins are notified at code creation for cafeteria; only notify on approval for other providers.
        if abono.forma_pago != "cafeteria":
            send_notificacion_admin_abono.delay(abono_info=abono_info)
        if abono.apoderado.comprobantes_transferencia:
            send_comprobante_abono.delay(abono_info=abono_info)
            if abono.apoderado.copia_notificaciones:
                send_copia_notificaciones_abono.delay(abono_info=abono_info)

    return redirect(url_for("apoderado_cliente.abono_detalle", codigo=codigo))


@pos_bp.route("/completa-pedido/<string:codigo>")
def completa_pedido(codigo):
    from flask_security import current_user

    pedido = db.session.execute(db.select(Pedido).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = (
        db.session.execute(db.select(Payment).filter_by(session_id=pedido.codigo_merchants)).scalar_one_or_none()
        if pedido and pedido.codigo_merchants
        else None
    )

    if (
        pedido
        and pago
        and pago.state == "processing"
        and (current_user.has_role("admin") or current_user.has_role("pos"))
    ):
        pago.state = "succeeded"
        pedido.pagado = True
        pedido.estado = EstadoPedido.PAGADO
        pedido.fecha_pago = datetime.now()
        db.session.commit()

        _process_payment_completion(pedido)

    return redirect(url_for("pos.pago_orden", orden=codigo))


def _compute_advertencias(menu, alumnos_item: list) -> list:
    """Return a list of warning dicts for a menu item and its assigned alumnos.

    Warns when a dish property (contiene_alergenos, es_vegano, es_vegetariano)
    is relevant to a student's declared dietary restrictions.  The purchase is
    never blocked – these are informational alerts only.
    """
    advertencias = []

    # Virtual / rezagados menus are SimpleNamespace objects without opciones
    if not hasattr(menu, "opciones"):
        return advertencias

    platos = [opcion.plato for opcion in menu.opciones]
    menu_contiene_alergenos = any(getattr(p, "contiene_alergenos", False) for p in platos)
    menu_es_vegano = any(getattr(p, "es_vegano", False) for p in platos)
    menu_es_vegetariano = any(getattr(p, "es_vegetariano", False) for p in platos)

    for alumno in alumnos_item:
        # Only real Alumno ORM objects carry restricciones
        if not hasattr(alumno, "restricciones") or not alumno.restricciones:
            continue
        restricciones = alumno.restricciones
        if not isinstance(restricciones, list):
            continue

        alergias = []
        nombres_lower = []
        tiene_vegano = False
        tiene_vegetariano = False
        for r in restricciones:
            nombre = r.get("nombre", "")
            motivo = r.get("motivo", "")
            if motivo == "Alergia":
                alergias.append(nombre)
            nombre_lower = nombre.lower()
            nombres_lower.append(nombre_lower)
            if "vegano" in nombre_lower or "vegan" in nombre_lower:
                tiene_vegano = True
            if "vegetariano" in nombre_lower or "vegetarian" in nombre_lower:
                tiene_vegetariano = True

        if menu_contiene_alergenos and alergias:
            advertencias.append({
                "alumno": alumno.nombre,
                "tipo": "warning",
                "mensaje": f"{alumno.nombre} tiene alergias declaradas ({', '.join(alergias)}) y este menú contiene alérgenos.",
            })

        if menu_es_vegano and tiene_vegano:
            advertencias.append({
                "alumno": alumno.nombre,
                "tipo": "info",
                "mensaje": f"Este menú incluye un plato vegano (aplica a {alumno.nombre}).",
            })
        elif menu_es_vegetariano and tiene_vegetariano:
            advertencias.append({
                "alumno": alumno.nombre,
                "tipo": "info",
                "mensaje": f"Este menú incluye una opción vegetariana (aplica a {alumno.nombre}).",
            })

    # Deduplicate while preserving order
    seen: set = set()
    result = []
    for adv in advertencias:
        key = (adv["alumno"], adv["tipo"], adv["mensaje"])
        if key not in seen:
            seen.add(key)
            result.append(adv)
    return result


def _process_payment_completion(pedido: Pedido) -> None:
    """Creates one OrdenCasino per item×alumno in pedido.extra_attrs after payment."""
    from datetime import date as _date
    from ..model import Alumno, MenuDiario, OrdenCasino

    items = pedido.extra_attrs or []

    # Guard: skip if orders were already created for this pedido
    existing = db.session.execute(
        db.select(OrdenCasino).filter_by(pedido_codigo=pedido.codigo).limit(1)
    ).scalar_one_or_none()
    if existing:
        return

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
            from ..routes import get_casino_timelimits
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

    db.session.commit()



# def reader():
#     return render_template("pos/reader.html")


# @pos_bp.route("/new-reading/")
# @pos_bp.route("/new-reading/<int:qr_data>")
# def nueva_lectura(qr_data):
#     registra_lectura(qr_data=qr_data)
#     return jsonify(qr_data)
