from flask import Blueprint, abort, render_template

core_bp = Blueprint("core", __name__)


@core_bp.route("/", methods=["GET"])
def index():
    return render_template("site/index.j2")


@core_bp.route("/buscar", methods=["GET"])
def buscar():
    return render_template("site/resultados.html")


@core_bp.route("/admin", methods=["GET"])
def admin():
    return render_template("seleccion.html")


@core_bp.route("/aiuda", methods=["GET"])
def ayuda():
    return render_template("core/ayuda.html")


@core_bp.route("/configuracion", methods=["GET"])
def configuracion():
    return render_template("core/configuracion.html")


def obtiene_menues(dia):
    from datetime import date, datetime

    from sqlalchemy import and_, or_

    from .model import MenuDiario

    if dia:
        try:
            fecha = datetime.strptime(dia, "%Y-%m-%d").date()
        except ValueError:
            return None
    else:
        fecha = date.today()

    menu_hoy = MenuDiario.query.filter(
        or_(MenuDiario.dia == fecha, MenuDiario.es_permanente == True), and_(MenuDiario.activo == True)
    ).all()
    return menu_hoy


@core_bp.route("/consulta/<dia>")
def consulta(dia):
    menues = obtiene_menues(dia)
    if not menues:
        abort(404)

    return render_template("casino/form_menu.html", menues=menues, dia=dia)
