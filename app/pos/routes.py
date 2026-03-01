from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request, url_for, redirect
from flask_security import current_user, login_required, roles_accepted

from ..database import db
from ..extensions import limiter
from ..model import EstadoPedido, Pedido, Abono, Payment, Alumno, MenuDiario, Settings
from .crud import PosController

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)
ctrl = PosController()


@pos_bp.route("/", methods=["GET"])
@roles_accepted("admin", "pos")
def index():
    alumnos_sin_tag = ctrl.get_alumnos_sin_tag()
    stats = ctrl.get_dashboard_stats()
    recientes = ctrl.get_ordenes_entregadas_hoy()
    return render_template("pos/dashboard.html", alumnos_sin_tag=alumnos_sin_tag, stats=stats, recientes=recientes)


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
    orden_data = None
    if orden:
        menu_diario = db.session.execute(
            db.select(MenuDiario).filter_by(slug=orden.menu_slug)
        ).scalar_one_or_none()
        courses = {}
        if menu_diario:
            courses = {
                "entradas": [p.nombre for p in menu_diario.entradas],
                "fondos": [p.nombre for p in menu_diario.fondos],
                "postres": [p.nombre for p in menu_diario.postres],
            }
        orden_data = {
            "id": orden.id,
            "menu_descripcion": orden.menu_descripcion,
            "menu_slug": orden.menu_slug,
            "entrega_url": url_for("pos.entrega_almuerzo", orden_id=orden.id),
            "courses": courses,
        }
    saldo_apoderado = alumno.apoderado.saldo_cuenta or 0
    menus_disponibles = []
    if not orden_data and not result["ya_entregado"] and saldo_apoderado > 0:
        menus_hoy = ctrl.get_menus_hoy()
        menus_disponibles = [
            {"slug": m.slug, "descripcion": m.descripcion, "precio": int(m.precio or 0)}
            for m in menus_hoy
            if m.precio and saldo_apoderado >= int(m.precio)
        ]
    return jsonify({
        "encontrado": True,
        "serial": serial,
        "alumno": {
            "id": alumno.id,
            "nombre": alumno.nombre,
            "curso": alumno.curso,
            "restricciones": alumno.restricciones or [],
        },
        "saldo_apoderado": saldo_apoderado,
        "orden": orden_data,
        "ya_entregado": result["ya_entregado"],
        "menus_disponibles": menus_disponibles,
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
    saldo_apoderado = alumno.apoderado.saldo_cuenta or 0
    menus_disponibles = []
    if not orden and not result["ya_entregado"] and saldo_apoderado > 0:
        menus_hoy = ctrl.get_menus_hoy()
        menus_disponibles = [
            {"slug": m.slug, "descripcion": m.descripcion, "precio": int(m.precio or 0)}
            for m in menus_hoy
            if m.precio and saldo_apoderado >= int(m.precio)
        ]
    return jsonify({
        "encontrado": True,
        "alumno": {
            "id": alumno.id,
            "nombre": alumno.nombre,
            "curso": alumno.curso,
            "restricciones": alumno.restricciones or [],
        },
        "saldo_apoderado": saldo_apoderado,
        "orden": {
            "id": orden.id,
            "menu_descripcion": orden.menu_descripcion,
            "menu_slug": orden.menu_slug,
            "entrega_url": url_for("pos.entrega_almuerzo", orden_id=orden.id),
        } if orden else None,
        "ya_entregado": result["ya_entregado"],
        "menus_disponibles": menus_disponibles,
    })


@pos_bp.route("/casino", methods=["GET"])
@roles_accepted("admin", "pos")
def casino():
    """POS Casino: NFC/QR tag scanner for lunch delivery."""
    recientes = ctrl.get_ordenes_entregadas_hoy()
    alumnos = ctrl.get_alumnos_con_almuerzo_pendiente()
    return render_template("pos/casino.html", recientes=recientes, alumnos=alumnos)


@pos_bp.route("/lector", methods=["GET"])
@roles_accepted("admin", "pos")
def lector():
    """Standalone kiosk NFC reader: full-screen canteen tag scanner for the mounted phone."""
    return render_template("pos/lector.html")


@pos_bp.route("/lector-qr", methods=["GET"])
@roles_accepted("admin", "pos")
def lector_qr():
    """Standalone kiosk QR reader: full-screen canteen QR scanner for the mounted phone.

    Camera facing mode is fixed by the Settings row with slug 'camara-lector-qr-casino'.
    Accepted values: 'frontal' (front camera) or 'trasera' (rear camera, default).
    """
    setting = db.session.execute(
        db.select(Settings).filter_by(slug="camara-lector-qr-casino")
    ).scalar_one_or_none()

    camara_val = setting.value if setting and setting.value is not None else None
    if isinstance(camara_val, str):
        camara = camara_val
    elif isinstance(camara_val, dict):
        camara = camara_val.get("camara") or camara_val.get("value") or ""
    else:
        camara = ""

    facing_mode = "user" if camara == "frontal" else "environment"
    return render_template("pos/lector-qr.html", facing_mode=facing_mode)


@pos_bp.route("/kiosko", methods=["GET"])
@roles_accepted("admin", "pos")
def kiosko():
    """Kiosk interface: sell a cash lunch to a student."""
    menus = ctrl.get_menus_hoy()
    alumnos = ctrl.get_alumnos_activos()
    return render_template("pos/kiosko.html", menus=menus, alumnos=alumnos)


@pos_bp.route("/venta-kiosko", methods=["POST"])
@roles_accepted("admin", "pos")
@limiter.limit("60 per minute")
def venta_kiosko():
    """Process a kiosk (cash) lunch sale.  Expects JSON body.

    Body: ``{"alumno_id": <int>, "menu_slug": <str>}``
    Returns JSON with the new OrdenCasino id.
    """
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

    menu = db.session.execute(db.select(MenuDiario).filter_by(slug=menu_slug)).scalar_one_or_none()
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


@pos_bp.route("/entrega-almuerzo/<int:orden_id>", methods=["POST"])
@roles_accepted("admin", "pos")
@limiter.limit("60 per minute")
def entrega_almuerzo(orden_id: int):
    """Mark an OrdenCasino as delivered (ENTREGADO)."""
    orden = ctrl.entregar_almuerzo(orden_id)
    if orden is None:
        return jsonify({"error": "Orden no encontrada o ya entregada"}), 404
    return jsonify({
        "ok": True,
        "orden_id": orden.id,
        "alumno_id": orden.alumno_id,
        "alumno_nombre": orden.alumno.nombre,
        "alumno_curso": orden.alumno.curso,
        "menu_slug": orden.menu_slug,
        "menu": orden.menu_descripcion or orden.menu_slug,
        "estado": orden.estado.value,
    })


@pos_bp.route("/api/canjear-credito", methods=["POST"])
@roles_accepted("admin", "pos")
@limiter.limit("60 per minute")
def api_canjear_credito():
    """Redeem today's lunch using the apoderado's credit balance (canje directo).

    Body: ``{"alumno_id": <int>, "menu_slug": <str>}``
    Returns JSON with the new OrdenCasino id on success.
    """
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

    menu = db.session.execute(db.select(MenuDiario).filter_by(slug=menu_slug)).scalar_one_or_none()
    if not menu:
        return jsonify({"error": "Menú no encontrado"}), 404

    orden = ctrl.canjear_con_credito(alumno, menu)
    if orden is None:
        return jsonify({"error": "Saldo insuficiente para canjear este menú"}), 422

    return jsonify({
        "ok": True,
        "orden_id": orden.id,
        "alumno_nombre": alumno.nombre,
        "alumno_curso": alumno.curso,
        "menu": menu.descripcion,
        "precio": int(menu.precio or 0),
        "nuevo_saldo": alumno.apoderado.saldo_cuenta or 0,
    }), 201


@pos_bp.route("/buscar-abono", methods=["GET", "POST"])
@roles_accepted("admin", "pos")
def buscar_abono():
    abono = pago = display_code = None
    codigo_buscado = ""
    if request.method == "POST":
        codigo_buscado = (request.form.get("codigo") or "").strip().upper()
        if codigo_buscado:
            abono, pago, display_code = ctrl.get_abono_by_codigo(codigo_buscado)
    return render_template(
        "pos/buscar-abono.html",
        abono=abono,
        pago=pago,
        display_code=display_code,
        codigo_buscado=codigo_buscado,
    )


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
