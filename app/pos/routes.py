from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request, url_for, redirect
from flask_security import current_user, login_required, roles_accepted

from ..database import db
from ..extensions import limiter
from ..model import EstadoPedido, Pedido, Abono, Payment, Alumno
from .crud import PosController

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)
ctrl = PosController()


@pos_bp.route("/", methods=["GET"])
@roles_accepted("admin", "pos")
def index():
    alumnos_sin_tag = ctrl.get_alumnos_sin_tag()
    return render_template("pos/dashboard.html", alumnos_sin_tag=alumnos_sin_tag)


@pos_bp.route("/valida_tag/<string:serial>", methods=["GET"])
@roles_accepted("admin", "pos")
def valida_tag(serial: str):
    alumno = ctrl.get_alumno_by_tag(serial)

    if not alumno:
        return jsonify({"error": "TAG no encontrado en el sistema", "serial": serial}), 404

    return (
        jsonify({"valid": True, "mensaje": f"TAG Asignado: Alumno {alumno.id}", "serial": serial}),
        200,
    )


@pos_bp.route("/api/alumno-tag/<string:serial>", methods=["GET"])
@roles_accepted("admin", "pos")
def api_alumno_tag(serial: str):
    """Full canteen scan endpoint: alumno info + today's pending lunch."""
    result = ctrl.get_alumno_con_orden(serial)
    alumno = result["alumno"]
    if not alumno:
        return jsonify({"encontrado": False, "serial": serial}), 404

    orden = result["orden"]
    return jsonify({
        "encontrado": True,
        "serial": serial,
        "alumno": {
            "id": alumno.id,
            "nombre": alumno.nombre,
            "curso": alumno.curso,
            "restricciones": alumno.restricciones or [],
        },
        "orden": {
            "id": orden.id,
            "menu_descripcion": orden.menu_descripcion,
            "menu_slug": orden.menu_slug,
            "entrega_url": url_for("pos.entrega_almuerzo", orden_id=orden.id),
        } if orden else None,
        "ya_entregado": result["ya_entregado"],
    })


@pos_bp.route("/api/alumno/<int:alumno_id>", methods=["GET"])
@roles_accepted("admin", "pos")
def api_alumno(alumno_id: int):
    """Canteen lookup by alumno ID (for manual entry): info + today's pending lunch."""
    result = ctrl.get_alumno_con_orden_by_id(alumno_id)
    alumno = result["alumno"]
    if not alumno:
        return jsonify({"encontrado": False, "alumno_id": alumno_id}), 404

    orden = result["orden"]
    return jsonify({
        "encontrado": True,
        "alumno": {
            "id": alumno.id,
            "nombre": alumno.nombre,
            "curso": alumno.curso,
            "restricciones": alumno.restricciones or [],
        },
        "orden": {
            "id": orden.id,
            "menu_descripcion": orden.menu_descripcion,
            "menu_slug": orden.menu_slug,
            "entrega_url": url_for("pos.entrega_almuerzo", orden_id=orden.id),
        } if orden else None,
        "ya_entregado": result["ya_entregado"],
    })


@pos_bp.route("/api/alumnos", methods=["GET"])
@roles_accepted("admin", "pos")
def api_alumnos():
    """JSON search endpoint for the kiosk alumno selector."""
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify([])
    alumnos = ctrl.buscar_alumnos(query)
    return jsonify([
        {"id": a.id, "nombre": a.nombre, "curso": a.curso}
        for a in alumnos
    ])


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
            abono, pago, display_code = ctrl.get_abono_by_codigo(codigo_buscado)

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
    abono, pago, display_code = ctrl.get_abono_by_codigo(codigo)

    if not abono:
        return jsonify({"error": "Abono no encontrado", "codigo": codigo}), 404

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
    """Canteen POS view: scan NFC/QR tag and deliver today's lunch."""
    recientes = ctrl.get_ordenes_entregadas_hoy()
    alumnos = ctrl.get_alumnos_activos()
    return render_template("pos/casino.html", recientes=recientes, alumnos=alumnos)


@pos_bp.route("/entrega-almuerzo/<int:orden_id>", methods=["POST"])
@roles_accepted("admin", "pos")
@limiter.limit("60 per minute")
def entrega_almuerzo(orden_id: int):
    """Mark an OrdenCasino as delivered. Returns JSON."""
    orden = ctrl.entregar_almuerzo(orden_id)
    if not orden:
        return jsonify({"error": "Orden no encontrada o ya entregada", "orden_id": orden_id}), 404
    return jsonify({
        "ok": True,
        "orden_id": orden.id,
        "alumno_nombre": orden.alumno.nombre,
        "alumno_curso": orden.alumno.curso,
        "menu": orden.menu_descripcion,
    })


@pos_bp.route("/kiosko", methods=["GET"])
@roles_accepted("admin", "pos")
def kiosko():
    """Kiosk interface: sell a cash lunch to a student."""
    menus = ctrl.get_menus_hoy()
    return render_template("pos/kiosko.html", menus=menus)


@pos_bp.route("/venta-kiosko", methods=["POST"])
@roles_accepted("admin", "pos")
@limiter.limit("60 per minute")
def venta_kiosko():
    """Process a kiosk (cash) lunch sale.  Expects JSON body.

    Body: ``{"alumno_id": <int>, "menu_slug": <str>}``
    Returns JSON with the new OrdenCasino id.
    """
    from ..model import MenuDiario as MD
    payload = request.get_json(force=True) or {}
    alumno_id = payload.get("alumno_id")
    menu_slug = payload.get("menu_slug")

    if not alumno_id or not menu_slug:
        return jsonify({"error": "alumno_id y menu_slug son requeridos"}), 400

    try:
        alumno_id_int = int(alumno_id)
    except (ValueError, TypeError):
        return jsonify({"error": "alumno_id inválido"}), 400

    alumno = db.session.get(Alumno, alumno_id_int)
    if not alumno:
        return jsonify({"error": "Alumno no encontrado"}), 404

    menu = db.session.execute(db.select(MD).filter_by(slug=menu_slug)).scalar_one_or_none()
    if not menu:
        return jsonify({"error": "Menú no encontrado"}), 404

    orden = ctrl.crear_orden_kiosko(alumno, menu)
    return jsonify({
        "ok": True,
        "orden_id": orden.id,
        "alumno_nombre": alumno.nombre,
        "alumno_curso": alumno.curso,
        "menu": menu.descripcion,
        "precio": int(menu.precio or 0),
    }), 201


@pos_bp.route("/completa-abono/<string:codigo>")
@roles_accepted("admin", "pos")
@limiter.limit("30 per minute")
def completa_abono(codigo):
    from ..tasks import send_comprobante_abono, send_notificacion_admin_abono, send_copia_notificaciones_abono

    abono, pago, _ = ctrl.get_abono_by_codigo(codigo)

    if abono and pago:
        approved = ctrl.approve_abono(abono, pago)
        if approved:
            from flask_merchants import merchants_audit
            merchants_audit.info(
                "abono_aprobado: codigo=%s apoderado_id=%s email=%r monto=%s nuevo_saldo=%s",
                abono.codigo,
                abono.apoderado.id,
                abono.apoderado.usuario.email,
                int(abono.monto),
                abono.apoderado.saldo_cuenta,
            )

            abono_info = {
                "id": abono.id,
                "codigo": abono.codigo,
                "monto": int(abono.monto),
                "forma_pago": abono.forma_pago,
                "descripcion": abono.descripcion,
                "apoderado_nombre": abono.apoderado.nombre,
                "apoderado_email": abono.apoderado.usuario.email,
                "saldo_cuenta": abono.apoderado.saldo_cuenta,
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
@limiter.limit("30 per minute")
def completa_pedido(codigo):
    from ..apoderado.controller import ApoderadoController
    apoderado_ctrl = ApoderadoController()

    pedido, pago = ctrl.get_pedido_with_payment(codigo)

    if pedido and pago:
        approved = ctrl.approve_pedido(pedido, pago)
        if approved:
            apoderado_ctrl.process_payment_completion(pedido)

    return redirect(url_for("apoderado_cliente.pago_orden", orden=codigo))


# def reader():
#     return render_template("pos/reader.html")


# @pos_bp.route("/new-reading/")
# @pos_bp.route("/new-reading/<int:qr_data>")
# def nueva_lectura(qr_data):
#     registra_lectura(qr_data=qr_data)
#     return jsonify(qr_data)
