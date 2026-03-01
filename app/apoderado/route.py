"""Apoderado blueprint - thin HTTP layer.

All database queries and business logic live in ApoderadoController.
Route functions only parse the request, call the controller, and return
a Flask response (render_template / redirect / jsonify).
"""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_security import current_user, login_required, roles_accepted  # type: ignore

from ..database import db
from ..extensions import limiter
from ..model import (
    Apoderado,
    MenuDiario,
    Payment,
    Pedido,
    Settings,
    EstadoPedido,
    Alumno,
    OrdenCasino,
)
from .controller import ApoderadoController

apoderado_bp = Blueprint("apoderado_cliente", __name__)
ctrl = ApoderadoController()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@apoderado_bp.route("/", methods=["GET"])
@roles_accepted("apoderado", "admin")
def index():
    apoderado = ctrl.get_apoderado(current_user)
    if not apoderado:
        return redirect(url_for("apoderado_cliente.wizp1"))
    stats = ctrl.get_spending_stats(apoderado)
    return render_template(
        "apoderado/dashboard.html", apoderado=apoderado, stats_por_alumno=stats
    )


# ---------------------------------------------------------------------------
# Registration wizard
# ---------------------------------------------------------------------------


@apoderado_bp.route("/wizard", methods=["GET"])
@apoderado_bp.route("/wizard/1", methods=["GET", "POST"])
@login_required
def wizp1():
    if request.method == "POST":
        apoderado = ctrl.create_apoderado(
            nombre=request.form["apoderado_nombre"],
            alumnos_count=request.form["alumnos"],
            user=current_user,
        )
        uds = current_app.extensions["user_datastore"]
        uds.add_role_to_user(current_user, "apoderado")
        db.session.commit()
        return redirect(url_for("apoderado_cliente.wizp2"))
    return render_template("apoderado/wizard-paso1.html")


@apoderado_bp.route("/wizard/2", methods=["GET", "POST"])
@login_required
def wizp2():
    apoderado = ctrl.get_apoderado(current_user)
    if not apoderado:
        return redirect(".wizp1")
    cursos = db.session.execute(
        db.select(Settings).filter_by(slug="cursos")
    ).scalar_one()
    if request.method == "POST":
        alumnos_data = []
        for num in range(1, apoderado.alumnos_registro + 1):
            restricciones_raw = request.form.get(f"restricciones_json_{num}", "[]")
            try:
                restricciones = json.loads(restricciones_raw)
                if not isinstance(restricciones, list):
                    restricciones = []
            except (json.JSONDecodeError, ValueError):
                restricciones = []
            alumnos_data.append(
                {
                    "nombre": request.form[f"nombre_alumno_{num}"],
                    "curso": request.form[f"curso_alumno_{num}"],
                    "edad": request.form[f"edad_alumno_{num}"],
                    "restricciones": restricciones,
                }
            )
        ctrl.create_alumnos(apoderado, alumnos_data)
        return redirect(url_for("apoderado_cliente.wizp3"))
    return render_template(
        "apoderado/wizard-paso2.html", apoderado=apoderado, cursos=cursos.value
    )


@apoderado_bp.route("/wizard/3", methods=["GET", "POST"])
@login_required
def wizp3():
    apoderado = ctrl.get_apoderado(current_user)
    if not apoderado:
        return redirect(".wizp1")
    if request.method == "POST":
        ctrl.update_preferences(
            apoderado,
            {
                "notificacion_comprobante": request.form.get(
                    "notificacion_comprobante"
                ),
                "notificacion_compra": request.form.get("notificacion_compra"),
                "informe_semanal": request.form.get("informe_semanal"),
                "tag_compartido": request.form.get("tag_compartido"),
                "correo_alternativo": request.form.get("correo_alternativo"),
                "monto_diario": request.form.get("monto_diario"),
                "monto_semanal": request.form.get("monto_semanal"),
                "limite_notificaciones": request.form.get("monto_semanal", 1500),
            },
        )
        from ..tasks import send_notificacion_admin_nuevo_apoderado
        from flask_merchants import merchants_audit

        payload = {
            "nombre_apoderado": apoderado.nombre,
            "email_apoderado": apoderado.usuario.email,
            "alumnos": [
                {"nombre": a.nombre, "curso": a.curso} for a in apoderado.alumnos
            ],
        }
        send_notificacion_admin_nuevo_apoderado.delay(payload)
        merchants_audit.info(
            "nuevo_apoderado_creado: id=%s nombre=%r email=%r alumnos=%d",
            apoderado.id,
            apoderado.nombre,
            apoderado.usuario.email,
            len(apoderado.alumnos),
        )
        return redirect(url_for("apoderado_cliente.wizp4"))
    return render_template("apoderado/wizard-paso3.html")


@apoderado_bp.route("/wizard/4", methods=["GET"])
@login_required
def wizp4():
    apoderado = ctrl.get_apoderado(current_user)
    return render_template("apoderado/wizard-paso4.html", apoderado=apoderado)


# ---------------------------------------------------------------------------
# Abonos (deposits)
# ---------------------------------------------------------------------------


@apoderado_bp.route("/abono", methods=["GET"])
@roles_accepted("apoderado", "admin")
def abono_form():
    return render_template("apoderado/abono.html")


@apoderado_bp.route("/abono", methods=["POST"])
@roles_accepted("apoderado", "admin")
@limiter.limit("5 per minute;30 per hour")
def abono():
    monto_raw = request.form.get("monto", "").strip()
    forma_pago = request.form.get("forma-de-pago", "")
    try:
        monto_decimal = Decimal(monto_raw)
    except InvalidOperation:
        flash(
            (
                "Por favor ingrese un monto."
                if not monto_raw
                else "El monto ingresado no es válido. Por favor ingrese un valor numérico."
            ),
            "danger",
        )
        return redirect(url_for("apoderado_cliente.abono_form"))

    nuevo_abono = ctrl.create_abono(current_user.apoderado, monto_decimal, forma_pago)

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
            success_url=url_for(
                "apoderado_cliente.abono_detalle",
                codigo=nuevo_abono.codigo,
                _external=True,
            ),
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

    elif forma_pago == "khipu":
        from ..extensions import flask_merchants

        session = flask_merchants.get_client("khipu").payments.create_checkout(
            amount=nuevo_abono.monto,
            currency="CLP",
            success_url=url_for(
                "apoderado_cliente.abono_detalle",
                codigo=nuevo_abono.codigo,
                _external=True,
            ),
            cancel_url=url_for(
                "apoderado_cliente.abono_detalle",
                codigo=nuevo_abono.codigo,
                _external=True,
            ),
            metadata={
                "abono_codigo": nuevo_abono.codigo,
                "apoderado_id": str(nuevo_abono.apoderado.id),
                "notify_url": url_for(
                    "merchants.webhook_provider", provider="khipu", _external=True
                ),
            },
        )
        pago = Payment(
            session_id=nuevo_abono.codigo,
            redirect_url=session.redirect_url,
            provider="khipu",
            amount=nuevo_abono.monto,
            currency="CLP",
            state="pending",
            metadata_json={
                "khipu_payment_id": session.session_id,
                "abono_codigo": nuevo_abono.codigo,
                "apoderado_id": str(nuevo_abono.apoderado.id),
            },
            request_payload={
                "abono_codigo": nuevo_abono.codigo,
                "monto": str(nuevo_abono.monto),
                "currency": "CLP",
                "apoderado_id": str(nuevo_abono.apoderado.id),
                "forma_pago": forma_pago,
            },
            response_payload=dict(session.raw),
        )
        db.session.add(pago)
        db.session.commit()

    return redirect(
        url_for("apoderado_cliente.abono_detalle", codigo=nuevo_abono.codigo)
    )


@apoderado_bp.route("/abono-detalle/<string:codigo>", methods=["GET"])
@roles_accepted("apoderado", "admin")
def abono_detalle(codigo):
    abono, pago, display_code = ctrl.get_abono(codigo)
    return render_template(
        "apoderado/detalle-abono.html",
        abono=abono,
        pago=pago,
        display_code=display_code,
    )


@apoderado_bp.route("/abonos", methods=["GET"])
@roles_accepted("apoderado", "admin")
def abonos():
    apoderado = ctrl.get_apoderado(current_user)
    if not apoderado:
        return redirect(url_for("core.index"))
    abonos_info = ctrl.get_abonos_info(apoderado)
    return render_template(
        "apoderado/abonos.html", abonos_info=abonos_info, apoderado=apoderado
    )


# ---------------------------------------------------------------------------
# Menu ordering
# ---------------------------------------------------------------------------


@apoderado_bp.route("/menu-casino", methods=["GET"])
@roles_accepted("apoderado", "admin")
def menu_casino():
    from sqlalchemy.orm import selectinload
    from ..routes import get_casino_timelimits, TIMEZONE_SANTIAGO
    from datetime import timedelta

    apoderado = db.session.execute(
        db.select(Apoderado)
        .filter_by(usuario=current_user)
        .options(selectinload(Apoderado.alumnos))
    ).scalar_one_or_none()
    alumnos = apoderado.alumnos if apoderado else []

    hora_limite, hora_rezagados, _ = get_casino_timelimits()
    ahora = datetime.now(TIMEZONE_SANTIAGO)
    today_date = ahora.date()
    valid_range_start = (
        (today_date + timedelta(days=1)).isoformat()
        if ahora.time() >= hora_rezagados
        else today_date.isoformat()
    )
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
    apoderado = ctrl.get_apoderado(current_user)
    if not apoderado:
        return redirect(url_for("core.index"))
    pedidos_info = ctrl.get_pedidos_for_apoderado(apoderado)
    return render_template(
        "apoderado/almuerzos.html", pedidos_info=pedidos_info, apoderado=apoderado
    )


@apoderado_bp.route("/alumno/<int:id>/toggle-activo", methods=["POST"])
@roles_accepted("apoderado", "admin")
def toggle_alumno_activo(id):
    from flask import abort

    alumno = db.session.execute(
        db.select(Alumno).filter_by(apoderado=current_user.apoderado, id=id)
    ).scalar_one_or_none()
    if not alumno:
        abort(404)
    ctrl.toggle_alumno_activo(alumno)
    return redirect(url_for("apoderado_cliente.index"))


# ---------------------------------------------------------------------------
# Student profile
# ---------------------------------------------------------------------------


@apoderado_bp.route("/ficha-alumno/<int:id>", methods=["GET"])
@roles_accepted("apoderado", "admin")
def ficha(id):
    alumno = db.session.execute(
        db.select(Alumno).filter_by(apoderado=current_user.apoderado, id=id)
    ).scalar_one()
    spending = ctrl.get_alumno_spending(alumno)
    return render_template("apoderado/ficha.html", alumno=alumno, **spending)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@apoderado_bp.route("/kiosko", methods=["GET"])
@roles_accepted("apoderado", "admin")
def kiosko():
    return render_template("apoderado/kiosko.html")


@apoderado_bp.route("/ajustes", methods=["GET", "POST"])
@roles_accepted("apoderado", "admin")
def ajustes():
    apoderado = ctrl.get_apoderado(current_user)
    if request.method == "POST":
        ctrl.update_ajustes(apoderado, current_user, request.form)
        flash("Cambios guardados correctamente.", "success")
        return redirect(url_for("apoderado_cliente.ajustes"))
    return render_template(
        "core/configuracion.html", apoderado=apoderado, current_user=current_user
    )


@apoderado_bp.route("/ajustes/restricciones", methods=["POST"])
@roles_accepted("apoderado", "admin")
def ajustes_restricciones():
    from flask import abort

    apoderado = ctrl.get_apoderado(current_user)
    if not apoderado:
        abort(403)
    nombre = request.form.get("nombre", "").strip()
    motivo = request.form.get("motivo", "").strip()
    alumno_ids = request.form.getlist("alumno_ids")
    if not nombre or not alumno_ids:
        flash("Debes ingresar un nombre y seleccionar al menos un alumno.", "danger")
        return redirect(url_for("apoderado_cliente.ajustes") + "#tab-restricciones")
    alumnos = [a for a in apoderado.alumnos if str(a.id) in alumno_ids]
    ctrl.add_restriccion_alumnos(alumnos, nombre, motivo or "Restringida por apoderado")
    flash("Restricción agregada correctamente.", "success")
    return redirect(url_for("apoderado_cliente.ajustes") + "#tab-restricciones")


@apoderado_bp.route("/alumno/<int:id>/delete-restriccion", methods=["POST"])
@roles_accepted("apoderado", "admin")
def delete_restriccion(id):
    from flask import abort

    alumno = db.session.execute(
        db.select(Alumno).filter_by(apoderado=current_user.apoderado, id=id)
    ).scalar_one_or_none()
    if not alumno:
        abort(404)
    try:
        index = int(request.form.get("index", -1))
    except (ValueError, TypeError):
        index = -1
    ctrl.delete_restriccion_alumno(alumno, index)
    flash("Restricción eliminada.", "success")
    return redirect(url_for("apoderado_cliente.ficha", id=id) + "#restricciones")


# ---------------------------------------------------------------------------
# Web ordering (parent-facing - moved from pos blueprint)
# ---------------------------------------------------------------------------


@apoderado_bp.route("/orden-web", methods=["POST"])
@roles_accepted("apoderado", "admin")
@limiter.limit("10 per minute;60 per hour")
def ordenweb():
    payload = request.get_json(force=True)
    apoderado = ctrl.get_apoderado(current_user)
    nueva_orden = ctrl.crea_orden(
        payload=payload["purchases"],
        apoderado_id=apoderado.id if apoderado else None,
    )
    return jsonify(
        {
            "status": "OK",
            "redirect_url": url_for("apoderado_cliente.pago_orden", orden=nueva_orden),
        }
    )


@apoderado_bp.route("/pago-orden/<orden>", methods=["GET", "POST"])
@roles_accepted("apoderado", "admin")
def pago_orden(orden):
    from types import SimpleNamespace
    from ..extensions import flask_merchants
    from ..routes import get_casino_timelimits

    pedido = db.session.execute(
        db.select(Pedido).filter_by(codigo=orden)
    ).scalar_one_or_none()
    apoderado = ctrl.get_apoderado(current_user)
    resumen = []
    pago = None
    display_code = ""
    total = Decimal(0)
    descuento_promocional = Decimal(0)
    alumnos_con_descuento: list = []

    if pedido:
        all_alumno_ids = [
            int(a["id"]) for item in pedido.extra_attrs for a in item.get("alumnos", [])
        ]
        alumnos_by_id = (
            {
                a.id: a
                for a in db.session.execute(
                    db.select(Alumno).filter(Alumno.id.in_(all_alumno_ids))
                )
                .scalars()
                .all()
            }
            if all_alumno_ids
            else {}
        )
        _, _, menu_rezagados_cfg = get_casino_timelimits()

        for item in pedido.extra_attrs:
            menu = db.session.execute(
                db.select(MenuDiario).filter_by(slug=item["slug"])
            ).scalar_one_or_none()
            if menu is None and item["slug"] == menu_rezagados_cfg["slug"]:
                menu = SimpleNamespace(
                    **{
                        k: menu_rezagados_cfg[k]
                        for k in ("slug", "descripcion", "precio")
                    }
                )
            alumnos_item = [
                alumnos_by_id.get(
                    int(a["id"]), {"nombre": a.get("nombre", "-"), "curso": None}
                )
                for a in item.get("alumnos", [])
            ]
            resumen.append(
                {
                    "fecha": item["date"],
                    "menu": item["slug"],
                    "nota": item["note"],
                    "detalle_menu": menu,
                    "alumnos": alumnos_item,
                    "advertencias": ctrl.compute_advertencias(menu, alumnos_item),
                }
            )
        total = sum(
            item["detalle_menu"].precio * len(item["alumnos"])
            for item in resumen
            if item["detalle_menu"] is not None
        )

        corte_setting = db.session.execute(
            db.select(Settings).filter_by(slug="corte_promocional")
        ).scalar_one_or_none()
        corte_cfg = corte_setting.value if corte_setting and corte_setting.value else {}
        descuento_info = ctrl.compute_descuento_promocional(resumen, corte_cfg)
        descuento_promocional = descuento_info["descuento_total"]
        alumnos_con_descuento = descuento_info["alumnos"]
        total = total - descuento_promocional

        if request.method == "POST":
            forma_pago = request.form.get("forma-de-pago", "cafeteria")
            descuento_saldo = Decimal(0)
            if apoderado and apoderado.saldo_cuenta and apoderado.saldo_cuenta >= 50:
                try:
                    raw = int(request.form.get("descuento_saldo", 0))
                    max_desc = min(apoderado.saldo_cuenta, int(total))
                    descuento_saldo = Decimal(max(0, min(raw, max_desc)))
                except (ValueError, TypeError):
                    pass
            monto_a_pagar = total - descuento_saldo

            if monto_a_pagar <= 0:
                if descuento_saldo > 0 and apoderado:
                    apoderado.saldo_cuenta = (apoderado.saldo_cuenta or 0) - int(
                        descuento_saldo
                    )
                pedido.precio_total = total
                pedido.estado = EstadoPedido.PAGADO
                pedido.pagado = True
                pedido.fecha_pago = datetime.now()
                db.session.commit()
                ctrl.process_payment_completion(pedido)
                return redirect(
                    url_for("apoderado_cliente.pago_orden", orden=pedido.codigo)
                )

            # SaldoProvider: pay the remaining amount entirely from account balance
            if forma_pago == "saldo":
                saldo_necesario = int(descuento_saldo) + int(monto_a_pagar)
                if (
                    not apoderado
                    or not apoderado.saldo_cuenta
                    or apoderado.saldo_cuenta < saldo_necesario
                ):
                    from flask import flash

                    flash(
                        "Saldo insuficiente para completar el pago con saldo de cuenta.",
                        "danger",
                    )
                    return redirect(
                        url_for("apoderado_cliente.pago_orden", orden=pedido.codigo)
                    )

                saldo_antes = apoderado.saldo_cuenta
                session = flask_merchants.get_client("saldo").payments.create_checkout(
                    amount=monto_a_pagar,
                    currency="CLP",
                    success_url=url_for(
                        "apoderado_cliente.pago_orden",
                        orden=pedido.codigo,
                        _external=True,
                    ),
                    cancel_url=url_for(
                        "apoderado_cliente.pago_orden",
                        orden=pedido.codigo,
                        _external=True,
                    ),
                    metadata={
                        "pedido_codigo": pedido.codigo,
                        "apoderado_id": str(apoderado.id),
                        "saldo_antes": saldo_antes,
                        "model_property": "saldo_cuenta",
                    },
                )
                # Deduct slider discount + saldo payment in one operation
                apoderado.saldo_cuenta = saldo_antes - saldo_necesario
                flask_merchants.save_session(
                    session,
                    model_class=Payment,
                    request_payload={
                        "pedido_codigo": pedido.codigo,
                        "monto": str(monto_a_pagar),
                        "currency": "CLP",
                        "forma_pago": "saldo",
                        "descuento_saldo": str(descuento_saldo),
                        "saldo_antes": str(saldo_antes),
                        "model_property": "saldo_cuenta",
                    },
                )
                flask_merchants.update_state(session.session_id, "succeeded")
                pedido.codigo_merchants = session.session_id
                pedido.precio_total = total
                pedido.estado = EstadoPedido.PAGADO
                pedido.pagado = True
                pedido.fecha_pago = datetime.now()
                db.session.commit()
                ctrl.process_payment_completion(pedido)
                # Leave a note on each OrdenCasino record indicating payment via saldo
                transaction_code = session.metadata.get("transaction_code", "")
                total_fmt = f"{int(total):,}".replace(",", ".")
                nota_saldo = f"Pagado con saldo de cuenta. Original: ${total_fmt}. Cod: {transaction_code}"
                ordenes = (
                    db.session.execute(
                        db.select(OrdenCasino).filter_by(pedido_codigo=pedido.codigo)
                    )
                    .scalars()
                    .all()
                )
                for oc in ordenes:
                    existing = oc.nota or ""
                    oc.nota = (f"{existing}. {nota_saldo}" if existing else nota_saldo)[
                        :255
                    ]
                db.session.commit()
                return redirect(
                    url_for("apoderado_cliente.pago_orden", orden=pedido.codigo)
                )

            session = flask_merchants.get_client(forma_pago).payments.create_checkout(
                amount=monto_a_pagar,
                currency="CLP",
                success_url=url_for(
                    "apoderado_cliente.pago_orden", orden=pedido.codigo, _external=True
                ),
                cancel_url=url_for(
                    "apoderado_cliente.pago_orden", orden=pedido.codigo, _external=True
                ),
                metadata={"pedido_codigo": pedido.codigo},
            )
            if descuento_saldo > 0 and apoderado:
                apoderado.saldo_cuenta = (apoderado.saldo_cuenta or 0) - int(
                    descuento_saldo
                )
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

            send_notificacion_pedido_pendiente.delay(
                {
                    "pedido_codigo": pedido.codigo,
                    "session_id": session.session_id,
                    "forma_pago": forma_pago,
                    "total": int(total),
                    "redirect_url": (
                        session.redirect_url if forma_pago != "cafeteria" else ""
                    ),
                    "pedido_url": url_for(
                        "apoderado_cliente.pago_orden",
                        orden=pedido.codigo,
                        _external=True,
                    ),
                    "items": [
                        {
                            "descripcion": (
                                i["detalle_menu"].descripcion
                                if i.get("detalle_menu")
                                else i["menu"]
                            ),
                            "fecha": i["fecha"],
                            "nota": i.get("nota", ""),
                            "precio": (
                                int(i["detalle_menu"].precio)
                                if i.get("detalle_menu")
                                else 0
                            ),
                            "alumnos_str": ", ".join(
                                (
                                    a.nombre
                                    if hasattr(a, "nombre")
                                    else a.get("nombre", "")
                                )
                                for a in i.get("alumnos", [])
                            ),
                            "alumnos": [
                                {"id": a.id if hasattr(a, "id") else a.get("id")}
                                for a in i.get("alumnos", [])
                            ],
                        }
                        for i in resumen
                    ],
                }
            )
            if forma_pago != "cafeteria" and session.redirect_url:
                return redirect(session.redirect_url)
            return redirect(
                url_for("apoderado_cliente.pago_orden", orden=pedido.codigo)
            )

        if pedido.codigo_merchants:
            pago = db.session.execute(
                db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
            ).scalar_one_or_none()
            display_code = (
                (pago.metadata_json or {}).get("display_code", "") if pago else ""
            )

    return render_template(
        "pos/venta-web.html",
        pedido=resumen,
        orden=pedido,
        total=total,
        pago=pago,
        display_code=display_code,
        apoderado=apoderado,
        descuento_promocional=descuento_promocional,
        alumnos_con_descuento=alumnos_con_descuento,
    )
