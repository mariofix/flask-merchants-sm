from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, url_for, redirect

from ..database import db
from ..model import Pedido, Abono, Payment, MenuDiario
from flask_merchants.core import PaymentStatus
from datetime import datetime

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/", methods=["GET"])
def index():
    return render_template("pos/dashboard.html")


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


@pos_bp.route("/pago-orden/<orden>", methods=["GET", "POST"])
def pago_orden(orden):
    pedido = db.session.execute(db.select(Pedido).filter_by(codigo=orden)).scalar_one_or_none()
    resumen = []
    pago = db.session.execute(db.select(Payment).filter_by(merchants_token=orden)).scalar_one_or_none()
    if pedido:
        for orden in pedido.extra_attrs:
            menu = db.session.execute(db.select(MenuDiario).filter_by(slug=orden["slug"])).scalar_one_or_none()

            resumen.append(
                {"fecha": orden["date"], "menu": orden["slug"], "nota": orden["note"], "detalle_menu": menu}
            )
        pago_process = None
        if request.method == "POST":
            forma_pago = request.form["forma-de-pago"]
            pago = Payment()
            pago.merchants_token = orden["slug"]
            pago.amount = Decimal(sum(item["detalle_menu"].precio for item in resumen))
            pago.currency = "CLP"
            pago.integration_slug = forma_pago

            db.session.add(pago)
            db.session.commit()

            pago_process = pago.process()

            if "transaction" in pago_process:
                pago.status = PaymentStatus.processing
                pago.integration_transaction = pago_process["transaction"]

                db.session.commit()
            if "url" in pago_process:
                return redirect(pago_process["url"])

    return render_template(
        "pos/venta-web.html",
        pedido=resumen,
        total=sum(item["detalle_menu"].precio for item in resumen),
        pago=pago,
    )


@pos_bp.route("/venta", methods=["POST"])
def venta():
    return render_template("pos/venta.html")


@pos_bp.route("/abono-web", methods=["GET", "POST"])
def abono():
    return render_template("pos/abono.html")


@pos_bp.route("/casino", methods=["GET"])
def casino():
    return render_template("pos/casino.html")


@pos_bp.route("/completa-abono/<string:codigo>")
def completa_abono(codigo):
    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = db.session.execute(db.select(Payment).filter_by(merchants_token=codigo)).scalar_one_or_none()
    if pago and abono and pago.status == PaymentStatus.processing:
        pago.status = PaymentStatus.paid
        pago.integration_response = {"fecha_pago": datetime.now().isoformat()}

        abono.apoderado.saldo_cuenta = int(abono.apoderado.saldo_cuenta + abono.monto)

        db.session.commit()

    return redirect(url_for("apoderado_cliente.abono_detalle", codigo=codigo))


# @pos_bp.route("/reader", methods=["GET"])
# def reader():
#     return render_template("pos/reader.html")


# @pos_bp.route("/new-reading/")
# @pos_bp.route("/new-reading/<int:qr_data>")
# def nueva_lectura(qr_data):
#     registra_lectura(qr_data=qr_data)
#     return jsonify(qr_data)
