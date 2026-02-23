from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, url_for, redirect
from flask_security import current_user, login_required, roles_accepted

from ..database import db
from ..model import EstadoPedido, Pedido, Abono, Payment, Alumno

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)



@pos_bp.route("/", methods=["GET"])
@roles_accepted("admin", "pos")
def index():
    alumnos_sin_tag = (
        db.session.execute(db.select(Alumno).filter_by(tag=None).order_by(Alumno.curso, Alumno.slug)).scalars().all()
    )
    return render_template("pos/dashboard.html", alumnos_sin_tag=alumnos_sin_tag)


@pos_bp.route("/valida_tag/<string:serial>", methods=["GET"])
@roles_accepted("admin", "pos")
def valida_tag(serial: str):
    alumno = db.session.execute(db.select(Alumno).filter_by(tag=serial.upper())).scalar_one_or_none()

    if not alumno:
        return jsonify({"error": "TAG no encontrado en el sistema", "serial": serial}), 404

    return (
        jsonify({"valid": True, "mensaje": f"TAG Asignado: Alumno {alumno.id}", "serial": serial}),
        200,
    )


@pos_bp.route("/venta", methods=["POST"])
@roles_accepted("admin", "pos")
def venta():
    return render_template("pos/venta.html")


@pos_bp.route("/buscar-abono", methods=["GET", "POST"])
@roles_accepted("admin", "pos")
def buscar_abono():
    abono = None
    pago = None
    display_code = ""
    codigo_buscado = ""

    if request.method == "POST":
        codigo_buscado = request.form.get("codigo", "").strip()
        if codigo_buscado:
            abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo_buscado)).scalar_one_or_none()
            if not abono:
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
@roles_accepted("admin", "pos")
def api_buscar_abono(codigo):
    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    if not abono:
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
@roles_accepted("admin", "pos")
def abono_web():
    return render_template("pos/abono.html")


@pos_bp.route("/casino", methods=["GET"])
@roles_accepted("admin", "pos")
def casino():
    return render_template("pos/casino.html")


@pos_bp.route("/kiosko", methods=["GET"])
@roles_accepted("admin", "pos")
def kiosko():
    """Casino/kiosk interface for cafeteria staff."""
    return render_template("pos/kiosko.html")


@pos_bp.route("/completa-abono/<string:codigo>")
@roles_accepted("admin", "pos")
def completa_abono(codigo):
    from ..tasks import send_comprobante_abono, send_notificacion_admin_abono, send_copia_notificaciones_abono

    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = db.session.execute(db.select(Payment).filter_by(session_id=codigo)).scalar_one_or_none()

    if abono and pago and pago.state == "processing":
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
        if abono.forma_pago != "cafeteria":
            send_notificacion_admin_abono.delay(abono_info=abono_info)
        if abono.apoderado.comprobantes_transferencia:
            send_comprobante_abono.delay(abono_info=abono_info)
            if abono.apoderado.copia_notificaciones:
                send_copia_notificaciones_abono.delay(abono_info=abono_info)

    return redirect(url_for("apoderado_cliente.abono_detalle", codigo=codigo))


@pos_bp.route("/completa-pedido/<string:codigo>")
@roles_accepted("admin", "pos")
def completa_pedido(codigo):
    from ..apoderado.controller import ApoderadoController
    ctrl = ApoderadoController()

    pedido = db.session.execute(db.select(Pedido).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = (
        db.session.execute(db.select(Payment).filter_by(session_id=pedido.codigo_merchants)).scalar_one_or_none()
        if pedido and pedido.codigo_merchants
        else None
    )

    if pedido and pago and pago.state == "processing":
        pago.state = "succeeded"
        pedido.pagado = True
        pedido.estado = EstadoPedido.PAGADO
        pedido.fecha_pago = datetime.now()
        db.session.commit()
        ctrl.process_payment_completion(pedido)

    # Redirect to the order summary page (parent-facing, on sabormirandiano.cl).
    # Staff complete the payment here; the order details page serves both roles.
    return redirect(url_for("apoderado_cliente.pago_orden", orden=codigo))


# def reader():
#     return render_template("pos/reader.html")


# @pos_bp.route("/new-reading/")
# @pos_bp.route("/new-reading/<int:qr_data>")
# def nueva_lectura(qr_data):
#     registra_lectura(qr_data=qr_data)
#     return jsonify(qr_data)
