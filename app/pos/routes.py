from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, url_for, redirect

from ..database import db
from ..extensions import flask_merchants
from ..model import EstadoPedido, Pedido, Abono, Payment, MenuDiario, Alumno

from datetime import datetime

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/", methods=["GET"])
def index():
    alumnos_sin_tag = (
        db.session.execute(db.select(Alumno).filter_by(tag=None).order_by(Alumno.curso, Alumno.slug)).scalars().all()
    )

    return render_template("pos/dashboard.html", alumnos_sin_tag=alumnos_sin_tag)


def creaOrden(payload):
    orden = Pedido()
    orden.extra_attrs = payload
    orden.precio_total = Decimal(0)
    db.session.add(orden)
    db.session.commit()

    return orden.codigo


@pos_bp.route("/orden-web", methods=["POST"])
def ordenweb():
    payload = request.get_json(force=True)
    ordenes = payload["purchases"]

    nueva_orden = creaOrden(ordenes)

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

    if pedido:
        for item in pedido.extra_attrs:
            menu = db.session.execute(db.select(MenuDiario).filter_by(slug=item["slug"])).scalar_one_or_none()
            resumen.append(
                {"fecha": item["date"], "menu": item["slug"], "nota": item["note"], "detalle_menu": menu}
            )
        total = sum(item["detalle_menu"].precio for item in resumen)

        if request.method == "POST":
            forma_pago = request.form.get("forma-de-pago", "cafeteria")
            session = flask_merchants.get_client(forma_pago).payments.create_checkout(
                amount=total,
                currency="CLP",
                success_url=url_for("pos.pago_orden", orden=pedido.codigo, _external=True),
                cancel_url=url_for("pos.pago_orden", orden=pedido.codigo, _external=True),
                metadata={"pedido_codigo": pedido.codigo},
            )
            flask_merchants.save_session(
                session,
                model_class=Payment,
                request_payload={
                    "pedido_codigo": pedido.codigo,
                    "monto": str(total),
                    "currency": "CLP",
                    "forma_pago": forma_pago,
                },
            )
            pedido.codigo_merchants = session.session_id
            pedido.precio_total = total
            pedido.estado = EstadoPedido.PENDIENTE
            if forma_pago == "cafeteria":
                flask_merchants.update_state(session.session_id, "processing")
            db.session.commit()
            return redirect(url_for("pos.pago_orden", orden=pedido.codigo))

        if pedido.codigo_merchants:
            pago = db.session.execute(
                db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
            ).scalar_one_or_none()
            display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""

    return render_template(
        "pos/venta-web.html",
        pedido=resumen,
        total=total,
        pago=pago,
        display_code=display_code,
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


# @pos_bp.route("/reader", methods=["GET"])
# def reader():
#     return render_template("pos/reader.html")


# @pos_bp.route("/new-reading/")
# @pos_bp.route("/new-reading/<int:qr_data>")
# def nueva_lectura(qr_data):
#     registra_lectura(qr_data=qr_data)
#     return jsonify(qr_data)
