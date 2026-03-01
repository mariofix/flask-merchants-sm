"""Staff blueprint - thin HTTP layer.

All database queries and business logic live in SchoolStaffController.
Route functions only parse the request, call the controller, and return
a Flask response (render_template / redirect / jsonify).
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_security import current_user, roles_accepted  # type: ignore

from ..database import db
from ..extensions import limiter
from ..model import MenuDiario, Payment, SchoolStaffPedido, EstadoPedido, SchoolStaff
from .controller import SchoolStaffController

staff_bp = Blueprint("staff", __name__)
ctrl = SchoolStaffController()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@staff_bp.route("/", methods=["GET"])
@roles_accepted("docente", "admin")
def index():
    staff = ctrl.get_staff(current_user)
    if not staff:
        abort(404)
    deuda = ctrl.get_deuda_actual(staff)
    deuda_mes = ctrl.get_deuda_mes_actual(staff)
    return render_template(
        "staff/dashboard.html",
        staff=staff,
        deuda=deuda,
        deuda_mes=deuda_mes,
    )


# ---------------------------------------------------------------------------
# Purchase history
# ---------------------------------------------------------------------------

@staff_bp.route("/almuerzos", methods=["GET"])
@roles_accepted("docente", "admin")
def almuerzos():
    staff = ctrl.get_staff(current_user)
    if not staff:
        abort(404)
    pedidos_info = ctrl.get_pedidos(staff)
    return render_template("staff/almuerzos.html", pedidos_info=pedidos_info, staff=staff)


# ---------------------------------------------------------------------------
# Menu ordering
# ---------------------------------------------------------------------------

@staff_bp.route("/menu-casino", methods=["GET"])
@roles_accepted("docente", "admin")
def menu_casino():
    from ..routes import get_casino_timelimits, TIMEZONE_SANTIAGO
    from datetime import timedelta

    staff = ctrl.get_staff(current_user)
    hora_limite, hora_rezagados, _ = get_casino_timelimits()
    ahora = datetime.now(TIMEZONE_SANTIAGO)
    today_date = ahora.date()
    valid_range_start = (
        (today_date + timedelta(days=1)).isoformat()
        if ahora.time() >= hora_rezagados
        else today_date.isoformat()
    )
    return render_template(
        "staff/menu-casino.html",
        staff=staff,
        today=today_date.isoformat(),
        valid_range_start=valid_range_start,
        hora_limite_pedido=hora_limite.strftime("%H:%M"),
        hora_limite_rezagados=hora_rezagados.strftime("%H:%M"),
    )


@staff_bp.route("/orden-web", methods=["POST"])
@roles_accepted("docente", "admin")
@limiter.limit("10 per minute;60 per hour")
def ordenweb():
    payload = request.get_json(force=True)
    staff = ctrl.get_staff(current_user)
    if not staff:
        return jsonify({"status": "error", "message": "Perfil de personal no encontrado"}), 400
    nueva_orden = ctrl.crea_pedido(
        payload=payload["purchases"],
        staff_id=staff.id,
    )
    return jsonify({"status": "OK", "redirect_url": url_for("staff.pago_orden", orden=nueva_orden)})


@staff_bp.route("/pago-orden/<orden>", methods=["GET", "POST"])
@roles_accepted("docente", "admin")
def pago_orden(orden):
    from types import SimpleNamespace
    from ..extensions import flask_merchants
    from ..routes import get_casino_timelimits

    pedido = db.session.execute(db.select(SchoolStaffPedido).filter_by(codigo=orden)).scalar_one_or_none()
    staff = ctrl.get_staff(current_user)
    resumen = []
    pago = None
    display_code = ""
    total = Decimal(0)

    if pedido:
        _, _, menu_rezagados_cfg = get_casino_timelimits()

        for item in (pedido.extra_attrs or []):
            menu = db.session.execute(
                db.select(MenuDiario).filter_by(slug=item["slug"])
            ).scalar_one_or_none()
            if menu is None and item["slug"] == menu_rezagados_cfg["slug"]:
                menu = SimpleNamespace(**{k: menu_rezagados_cfg[k] for k in ("slug", "descripcion", "precio")})
            resumen.append({
                "fecha": item["date"],
                "menu": item["slug"],
                "nota": item["note"],
                "detalle_menu": menu,
            })
        total = sum(
            item["detalle_menu"].precio
            for item in resumen
            if item["detalle_menu"] is not None
        )

        if request.method == "POST":
            forma_pago = request.form.get("forma-de-pago", "cafeteria")

            if forma_pago == "cuenta":
                # Post-pay: charge to the staff member's running tab
                if not ctrl.puede_comprar(staff, total):
                    flash("Límite de cuenta excedido. No es posible agregar más deuda.", "danger")
                    return redirect(url_for("staff.pago_orden", orden=pedido.codigo))
                pedido.precio_total = total
                pedido.estado = EstadoPedido.PAGADO
                pedido.pagado = True
                pedido.fecha_pago = datetime.now()
                db.session.commit()
                ctrl.process_payment_completion(pedido)
                return redirect(url_for("staff.pago_orden", orden=pedido.codigo))

            # External payment providers (cafeteria, khipu, etc.)
            session = flask_merchants.get_client(forma_pago).payments.create_checkout(
                amount=total,
                currency="CLP",
                success_url=url_for("staff.pago_orden", orden=pedido.codigo, _external=True),
                cancel_url=url_for("staff.pago_orden", orden=pedido.codigo, _external=True),
                metadata={"pedido_codigo": pedido.codigo, "staff_id": str(staff.id)},
            )
            flask_merchants.save_session(
                session,
                model_class=Payment,
                request_payload={
                    "pedido_codigo": pedido.codigo,
                    "monto": str(total),
                    "currency": "CLP",
                    "forma_pago": forma_pago,
                    "staff_id": str(staff.id),
                },
            )
            pedido.codigo_merchants = session.session_id
            pedido.precio_total = total
            pedido.estado = EstadoPedido.PENDIENTE
            if forma_pago == "cafeteria":
                flask_merchants.update_state(session.session_id, "processing")
            db.session.commit()

            if forma_pago != "cafeteria" and session.redirect_url:
                return redirect(session.redirect_url)
            return redirect(url_for("staff.pago_orden", orden=pedido.codigo))

        if pedido.codigo_merchants:
            pago = db.session.execute(
                db.select(Payment).filter_by(session_id=pedido.codigo_merchants)
            ).scalar_one_or_none()
            display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""

    return render_template(
        "staff/pago-orden.html",
        pedido=resumen, orden=pedido, total=total,
        pago=pago, display_code=display_code, staff=staff,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@staff_bp.route("/ajustes", methods=["GET", "POST"])
@roles_accepted("docente", "admin")
def ajustes():
    staff = ctrl.get_staff(current_user)
    if not staff:
        abort(404)
    if request.method == "POST":
        ctrl.update_ajustes(staff, current_user, request.form)
        flash("Cambios guardados correctamente.", "success")
        return redirect(url_for("staff.ajustes"))
    return render_template("staff/ajustes.html", staff=staff, current_user=current_user)
