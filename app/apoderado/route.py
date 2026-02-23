from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from ..database import db
from ..model import Apoderado, EstadoAlmuerzo, EstadoPedido, OrdenCasino, Settings, Alumno, Abono, Payment, Pedido
from .controller import ApoderadoController
from slugify import slugify
from flask_security import current_user, roles_required, roles_accepted, login_required  # type: ignore
from sqlalchemy import func, and_

apoderado_bp = Blueprint("apoderado_cliente", __name__)
apoderado_controller = ApoderadoController()


@apoderado_bp.before_request
def enforce_website_domain():
    """Redirect to the public website domain when SABORMIRANDIANO_HOST is configured."""
    host = current_app.config.get("SABORMIRANDIANO_HOST", "")
    if host and request.host.split(":")[0] != host:
        return redirect(f"https://{host}{request.full_path}", 301)


@apoderado_bp.route("/", methods=["GET"])
@roles_accepted("apoderado", "admin")
def index():
    apoderado = None
    if current_user.has_role("apoderado"):
        apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one_or_none()
    if not apoderado and current_user.has_role("admin"):
        return redirect(url_for("apoderado_cliente.wizp1"))
    if not apoderado and not current_user.has_role("admin"):
        return redirect(url_for("core.index"))
    if not apoderado and current_user.has_role("apoderado"):
        return redirect(url_for("apoderado_cliente.wizp1"))

    today = date.today()
    seven_days_ago = today - timedelta(days=6)

    stats_por_alumno: dict[int, dict] = {}
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
        stats_por_alumno[alumno.id] = {
            "gasto_hoy": int(gasto_hoy),
            "gasto_semana": int(gasto_semana),
        }

    return render_template("apoderado/dashboard.html", apoderado=apoderado, stats_por_alumno=stats_por_alumno)


@apoderado_bp.route("/wizard", methods=["GET"])
@apoderado_bp.route("/wizard/1", methods=["GET", "POST"])
@login_required
def wizp1():

    if request.method == "POST":
        nombre = request.form["apoderado_nombre"]
        alumnos = request.form["alumnos"]

        apoderado = Apoderado()
        apoderado.nombre = nombre
        apoderado.alumnos_registro = int(alumnos)
        apoderado.usuario_id = current_user.id
        db.session.add(apoderado)

        uds = current_app.extensions["user_datastore"]
        uds.add_role_to_user(current_user, "apoderado")

        db.session.commit()

        return redirect(url_for("apoderado_cliente.wizp2"))

    return render_template("apoderado/wizard-paso1.html")


@apoderado_bp.route("/wizard/2", methods=["GET", "POST"])
@login_required
def wizp2():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    cursos = db.session.execute(db.select(Settings).filter_by(slug="cursos")).scalar_one()
    if request.method == "POST":
        for num in range(1, apoderado.alumnos_registro + 1):
            restricciones_raw = request.form.get(f"restricciones_json_{num}", "[]")
            try:
                restricciones = json.loads(restricciones_raw)
                if not isinstance(restricciones, list):
                    restricciones = []
            except (json.JSONDecodeError, ValueError):
                restricciones = []
            nuevo_arr = {
                "nombre": request.form[f"nombre_alumno_{num}"],
                "curso": request.form[f"curso_alumno_{num}"],
                "edad": request.form[f"edad_alumno_{num}"],
            }
            nuevo = Alumno()
            nuevo.slug = slugify(f"{nuevo_arr.get("nombre", "")} {nuevo_arr.get("edad", "")}")
            nuevo.nombre = nuevo_arr.get("nombre", "")
            nuevo.curso = nuevo_arr.get("curso", "")
            nuevo.apoderado = apoderado
            nuevo.restricciones = restricciones
            db.session.add(nuevo)
            del nuevo
        db.session.commit()
        return redirect(url_for("apoderado_cliente.wizp3"))

    return render_template("apoderado/wizard-paso2.html", apoderado=apoderado, cursos=cursos.value)


@apoderado_bp.route("/wizard/3", methods=["GET", "POST"])
@login_required
def wizp3():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    if request.method == "POST":
        notificacion_compra = request.form.get("notificacion_compra", False)
        notificacion_comprobante = request.form.get("notificacion_comprobante", False)
        informe_semanal = request.form.get("informe_semanal", False)
        tag_compartido = request.form.get("tag_compartido", False)
        correo_alternativo = request.form.get("correo_alternativo", False)
        monto_diario = request.form.get("monto_diario", False)
        monto_semanal = request.form.get("monto_semanal", False)
        limite_notificaciones = request.form.get("monto_semanal", 1500)
        apoderado.comprobantes_transferencia = bool(notificacion_comprobante)
        apoderado.notificacion_compra = bool(notificacion_compra)
        apoderado.informe_semanal = bool(informe_semanal)
        apoderado.tag_compartido = bool(tag_compartido)
        apoderado.copia_notificaciones = correo_alternativo
        apoderado.maximo_diario = int(monto_diario)
        apoderado.maximo_semanal = int(monto_semanal)
        apoderado.limite_notificacion = int(limite_notificaciones)
        apoderado.saldo_cuenta = 0

        for alumno in apoderado.alumnos:
            alumno.maximo_diario = apoderado.maximo_diario
            alumno.maximo_semanal = apoderado.maximo_semanal

        # wizard_completado = Settings()
        # wizard_completado.user_id = current_user.id
        # wizard_completado.slug = "wizard"
        # wizard_completado.value = {"status": "ok"}
        # db.session.add(wizard_completado)

        db.session.commit()

        from ..tasks import send_notificacion_admin_nuevo_apoderado
        from flask_merchants import merchants_audit
        send_notificacion_admin_nuevo_apoderado.delay({
            "nombre_apoderado": apoderado.nombre,
            "email_apoderado": apoderado.usuario.email,
            "alumnos": [{"nombre": a.nombre, "curso": a.curso} for a in apoderado.alumnos],
        })
        merchants_audit.info(
            "nuevo_apoderado_creado: id=%s nombre=%r email=%r alumnos=%d",
            apoderado.id,
            apoderado.nombre,
            apoderado.usuario.email,
            len(apoderado.alumnos),
        )
        merchants_audit.info(
            "nuevo_apoderado_notificado: id=%s nombre=%r email=%r",
            apoderado.id,
            apoderado.nombre,
            apoderado.usuario.email,
        )

        send_notificacion_admin_nuevo_apoderado.delay(
            {
                "nombre_apoderado": apoderado.nombre,
                "email_apoderado": apoderado.usuario.email,
                "alumnos": [{"nombre": a.nombre, "curso": a.curso} for a in apoderado.alumnos],
            }
        )

        return redirect(url_for("apoderado_cliente.wizp4"))

    return render_template("apoderado/wizard-paso3.html")


@apoderado_bp.route("/wizard/4", methods=["GET"])
@login_required
def wizp4():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    ## Notificar a Admins
    correo = render_template("core/emails/nuevo_apoderado.html", apoderado=apoderado)

    return render_template("apoderado/wizard-paso4.html", apoderado=apoderado)


@apoderado_bp.route("/abono", methods=["GET"])
@roles_accepted("apoderado", "admin")
def abono_form():
    return render_template("apoderado/abono.html")


@apoderado_bp.route("/abono", methods=["POST"])
@roles_accepted("apoderado", "admin")
def abono():
    monto = request.form.get("monto", "").strip()
    forma_pago = request.form.get("forma-de-pago", "")
    try:
        monto_decimal = Decimal(monto)
    except InvalidOperation:
        if not monto:
            flash("Por favor ingrese un monto.", "danger")
        else:
            flash("El monto ingresado no es válido. Por favor ingrese un valor numérico.", "danger")
        return redirect(url_for("apoderado_cliente.abono_form"))
    nuevo_abono = Abono()
    nuevo_abono.monto = monto_decimal
    nuevo_abono.apoderado = current_user.apoderado
    nuevo_abono.descripcion = "Abono Web"
    nuevo_abono.forma_pago = forma_pago

    db.session.add(nuevo_abono)
    db.session.commit()

    from flask_merchants import merchants_audit
    merchants_audit.info(
        "abono_creado: codigo=%s apoderado_id=%s email=%r monto=%s forma_pago=%r",
        nuevo_abono.codigo,
        nuevo_abono.apoderado.id,
        nuevo_abono.apoderado.usuario.email,
        nuevo_abono.monto,
        nuevo_abono.forma_pago,
    )

    if forma_pago == "cafeteria":
        from ..extensions import flask_merchants

        session = flask_merchants.get_client("cafeteria").payments.create_checkout(
            amount=nuevo_abono.monto,
            currency="CLP",
            success_url=url_for("apoderado_cliente.abono_detalle", codigo=nuevo_abono.codigo, _external=True),
            cancel_url=url_for("apoderado_cliente.index", _external=True),
            metadata={
                "abono_codigo": nuevo_abono.codigo,
                "apoderado_id": str(nuevo_abono.apoderado.id),
            },
        )
        flask_merchants.save_session(
            session,
            model_class=Payment,
            request_payload={
                "abono_codigo": nuevo_abono.codigo,
                "monto": str(nuevo_abono.monto),
                "currency": "CLP",
                "apoderado_id": str(nuevo_abono.apoderado.id),
                "forma_pago": forma_pago,
            },
        )
        # Marcar como "processing" – esperando pago presencial
        flask_merchants.update_state(nuevo_abono.codigo, "processing")

        from ..tasks import send_notificacion_abono_creado

        send_notificacion_abono_creado.delay(
            abono_info={
                "codigo": nuevo_abono.codigo,
                "monto": int(nuevo_abono.monto),
                "forma_pago": nuevo_abono.forma_pago,
                "descripcion": nuevo_abono.descripcion,
                "apoderado_nombre": nuevo_abono.apoderado.nombre,
                "apoderado_email": nuevo_abono.apoderado.usuario.email,
                "saldo_cuenta": nuevo_abono.apoderado.saldo_cuenta or 0,
                "comprobantes_transferencia": nuevo_abono.apoderado.comprobantes_transferencia,
                "copia_notificaciones": nuevo_abono.apoderado.copia_notificaciones,
            }
        )

    return redirect(url_for("apoderado_cliente.abono_detalle", codigo=nuevo_abono.codigo))


@apoderado_bp.route("/abono-detalle/<string:codigo>", methods=["GET"])
@login_required
def abono_detalle(codigo):
    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = db.session.execute(db.select(Payment).filter_by(session_id=codigo)).scalar_one_or_none()
    display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""
    print(f"{abono=}")
    return render_template("apoderado/detalle-abono.html", abono=abono, pago=pago, display_code=display_code)


@apoderado_bp.route("/menu-casino", methods=["GET"])
@login_required
def menu_casino():
    from sqlalchemy.orm import selectinload
    from ..routes import get_casino_timelimits, TIMEZONE_SANTIAGO

    alumnos = []
    apoderado = db.session.execute(
        db.select(Apoderado).filter_by(usuario=current_user).options(selectinload(Apoderado.alumnos))
    ).scalar_one_or_none()
    if apoderado:
        alumnos = apoderado.alumnos

    hora_limite, hora_rezagados, _ = get_casino_timelimits()
    ahora = datetime.now(TIMEZONE_SANTIAGO)
    today_date = ahora.date()

    # After the rezagados cutoff (e.g. 14:00) today is closed; move valid range to tomorrow
    if ahora.time() >= hora_rezagados:
        valid_range_start = (today_date + timedelta(days=1)).isoformat()
    else:
        valid_range_start = today_date.isoformat()

    return render_template(
        "apoderado/menu-casino.html",
        alumnos=alumnos,
        today=today_date.isoformat(),
        valid_range_start=valid_range_start,
        hora_limite_pedido=hora_limite.strftime("%H:%M"),
        hora_limite_rezagados=hora_rezagados.strftime("%H:%M"),
    )


@apoderado_bp.route("/almuerzos", methods=["GET"])
@roles_accepted("apoderado", "admin")
def almuerzos():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one_or_none()
    if not apoderado:
        return redirect(url_for("core.index"))

    # Primary query: pedidos linked directly via apoderado_id
    pedidos_directos = db.session.execute(
        db.select(Pedido)
        .filter_by(apoderado_id=apoderado.id)
        .order_by(Pedido.fecha_pedido.desc())
        .limit(30)
    ).scalars().all()

    # Fallback: legacy pedidos discoverable via OrdenCasino for any of the apoderado's alumnos
    alumno_ids = [a.id for a in apoderado.alumnos]
    codigos_directos = {p.codigo for p in pedidos_directos}
    pedidos_legacy = []
    if alumno_ids:
        codigos_ordenes = db.session.execute(
            db.select(OrdenCasino.pedido_codigo)
            .where(OrdenCasino.alumno_id.in_(alumno_ids))
            .distinct()
        ).scalars().all()
        codigos_legacy = [c for c in codigos_ordenes if c not in codigos_directos]
        if codigos_legacy:
            pedidos_legacy = db.session.execute(
                db.select(Pedido).where(Pedido.codigo.in_(codigos_legacy))
            ).scalars().all()

    # Combine and sort by fecha_pedido descending
    todos_pedidos = sorted(
        list(pedidos_directos) + list(pedidos_legacy),
        key=lambda p: p.fecha_pedido,
        reverse=True,
    )[:30]

    # Build enriched list with payment info and related OrdenCasino records
    pedidos_info = []
    for pedido in todos_pedidos:
        pago = None
        if pedido.codigo_merchants:
            pago = db.session.execute(
                db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
            ).scalar_one_or_none()
        ordenes = db.session.execute(
            db.select(OrdenCasino).filter_by(pedido_codigo=pedido.codigo)
        ).scalars().all()
        pedidos_info.append({"pedido": pedido, "pago": pago, "ordenes": ordenes})

    return render_template("apoderado/almuerzos.html", pedidos_info=pedidos_info, apoderado=apoderado)




@apoderado_bp.route("/ficha-alumno/<int:id>", methods=["GET"])
@roles_accepted("apoderado", "admin")
def ficha(id):
    alumno = db.session.execute(db.select(Alumno).filter_by(apoderado=current_user.apoderado, id=id)).scalar_one()

    today = date.today()

    def _sum_ordenes(desde: date) -> int:
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

    uso_24h = _sum_ordenes(today)
    uso_7d = _sum_ordenes(today - timedelta(days=6))
    uso_14d = _sum_ordenes(today - timedelta(days=13))

    return render_template("apoderado/ficha.html", alumno=alumno, uso_24h=uso_24h, uso_7d=uso_7d, uso_14d=uso_14d)


@apoderado_bp.route("/abonos", methods=["GET"])
@roles_accepted("apoderado", "admin")
def abonos():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one_or_none()
    if not apoderado:
        return redirect(url_for("core.index"))

    abono_list = apoderado.abonos
    codigos = [a.codigo for a in abono_list]
    pagos_by_codigo = {}
    if codigos:
        pagos = db.session.execute(
            db.select(Payment).where(Payment.session_id.in_(codigos))
        ).scalars().all()
        pagos_by_codigo = {p.session_id: p for p in pagos}

    abonos_info = [{"abono": a, "pago": pagos_by_codigo.get(a.codigo)} for a in abono_list]

    return render_template("apoderado/abonos.html", abonos_info=abonos_info, apoderado=apoderado)


@apoderado_bp.route("/ajustes", methods=["GET", "POST"])
@login_required
def ajustes():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one_or_none()

    if request.method == "POST":
        if apoderado:
            apoderado.nombre = request.form.get("nombre", apoderado.nombre)
            apoderado.comprobantes_transferencia = bool(request.form.get("comprobantes_transferencia"))
            apoderado.notificacion_compra = bool(request.form.get("notificacion_compra"))
            apoderado.informe_semanal = bool(request.form.get("informe_semanal"))
            apoderado.copia_notificaciones = request.form.get("copia_notificaciones", apoderado.copia_notificaciones)
            monto_diario = request.form.get("maximo_diario")
            if monto_diario:
                try:
                    apoderado.maximo_diario = int(monto_diario)
                except ValueError:
                    pass
            monto_semanal = request.form.get("maximo_semanal")
            if monto_semanal:
                try:
                    apoderado.maximo_semanal = int(monto_semanal)
                except ValueError:
                    pass
        phone = request.form.get("phone")
        if phone:
            current_user.username = phone
        db.session.commit()
        return redirect(url_for("apoderado_cliente.ajustes"))

    return render_template(
        "core/configuracion.html",
        apoderado=apoderado,
        current_user=current_user,
    )


# ---------------------------------------------------------------------------
# Web ordering routes (moved from pos blueprint — these are parent-facing)
# ---------------------------------------------------------------------------

@apoderado_bp.route("/orden-web", methods=["POST"])
@login_required
def ordenweb():
    from ..extensions import flask_merchants
    from ..model import MenuDiario
    payload = request.get_json(force=True)
    ordenes = payload["purchases"]

    apoderado_id = None
    apoderado = db.session.execute(
        db.select(Apoderado).filter_by(usuario=current_user)
    ).scalar_one_or_none()
    if apoderado:
        apoderado_id = apoderado.id

    nueva_orden = _crea_orden(ordenes, apoderado_id=apoderado_id)

    return jsonify(
        {
            "status": "OK",
            "redirect_url": url_for("apoderado_cliente.pago_orden", orden=nueva_orden),
        }
    )


@apoderado_bp.route("/pago-orden/<orden>", methods=["GET", "POST"])
@login_required
def pago_orden(orden):
    from ..extensions import flask_merchants
    from ..model import MenuDiario
    from ..routes import get_casino_timelimits
    from types import SimpleNamespace

    pedido = db.session.execute(db.select(Pedido).filter_by(codigo=orden)).scalar_one_or_none()
    resumen = []
    pago = None
    display_code = ""
    total = Decimal(0)

    apoderado = db.session.execute(
        db.select(Apoderado).filter_by(usuario=current_user)
    ).scalar_one_or_none()

    if pedido:
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

        _, _, menu_rezagados_cfg = get_casino_timelimits()

        for item in pedido.extra_attrs:
            menu = db.session.execute(db.select(MenuDiario).filter_by(slug=item["slug"])).scalar_one_or_none()
            if menu is None and item["slug"] == menu_rezagados_cfg["slug"]:
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
                if descuento_saldo > 0:
                    apoderado.saldo_cuenta = (apoderado.saldo_cuenta or 0) - int(descuento_saldo)
                pedido.precio_total = total
                pedido.estado = EstadoPedido.PAGADO
                pedido.pagado = True
                pedido.fecha_pago = datetime.now()
                db.session.commit()
                _process_payment_completion(pedido)
                return redirect(url_for("apoderado_cliente.pago_orden", orden=pedido.codigo))

            session = flask_merchants.get_client(forma_pago).payments.create_checkout(
                amount=monto_a_pagar,
                currency="CLP",
                success_url=url_for("apoderado_cliente.pago_orden", orden=pedido.codigo, _external=True),
                cancel_url=url_for("apoderado_cliente.pago_orden", orden=pedido.codigo, _external=True),
                metadata={"pedido_codigo": pedido.codigo},
            )
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

            from ..tasks import send_notificacion_pedido_pendiente
            pedido_url = url_for("apoderado_cliente.pago_orden", orden=pedido.codigo, _external=True)
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
            return redirect(url_for("apoderado_cliente.pago_orden", orden=pedido.codigo))

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


def _crea_orden(payload, apoderado_id=None):
    orden = Pedido()
    orden.extra_attrs = payload
    orden.precio_total = Decimal(0)
    if apoderado_id is not None:
        orden.apoderado_id = apoderado_id
    db.session.add(orden)
    db.session.commit()
    return orden.codigo


def _compute_advertencias(menu, alumnos_item: list) -> list:
    """Return a list of warning dicts for a menu item and its assigned alumnos."""
    advertencias = []

    if not hasattr(menu, "opciones"):
        return advertencias

    platos = [opcion.plato for opcion in menu.opciones]
    menu_contiene_alergenos = any(getattr(p, "contiene_alergenos", False) for p in platos)
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
            nombre = r.get("nombre", "")
            motivo = r.get("motivo", "")
            if motivo == "Alergia":
                alergias.append(nombre)
            nombre_lower = nombre.lower()
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
    from ..routes import get_casino_timelimits

    items = pedido.extra_attrs or []

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
