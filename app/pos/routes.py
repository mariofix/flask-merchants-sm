from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, url_for

from ..database import db
from ..model import Orden

# from .reader import registra_lectura

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/", methods=["GET"])
def index():
    return render_template("pos/dashboard.html")


def creaOrden(payload):
    orden = Orden()
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


@pos_bp.route("/pago-orden/<orden>")
def pago_orden(orden):
    return render_template("pos/venta-web.html", orden=orden)


@pos_bp.route("/venta", methods=["POST"])
def venta():
    return render_template("pos/venta.html")


@pos_bp.route("/casino", methods=["GET"])
def casino():
    return render_template("pos/casino.html")


@pos_bp.route("/reader", methods=["GET"])
def reader():
    return render_template("pos/reader.html")


# @pos_bp.route("/new-reading/")
# @pos_bp.route("/new-reading/<int:qr_data>")
# def nueva_lectura(qr_data):
#     registra_lectura(qr_data=qr_data)
#     return jsonify(qr_data)
