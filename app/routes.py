from flask import Blueprint, abort, render_template
from .model import MenuDiario
from .database import db
from datetime import date, datetime
from collections import OrderedDict
from sqlalchemy import and_, or_, select
from flask_login import login_required
from flask_security.decorators import roles_required
import locale

core_bp = Blueprint("core", __name__)


@core_bp.route("/", methods=["GET"])
def index():
    today = date.today()

    stmt = select(MenuDiario.dia).where(MenuDiario.dia >= today).distinct().order_by(MenuDiario.dia.asc()).limit(5)

    lista_dias = db.session.execute(stmt).scalars().all()
    payload = OrderedDict()
    payload_dias = OrderedDict()
    for dia in lista_dias:
        payload[dia.isoformat()] = obtiene_menues(dia.isoformat())

        locale.setlocale(locale.LC_TIME, "es_CL.utf8")
        payload_dias[dia.isoformat()] = dia.strftime("%A, %d de %B de %Y")

    return render_template("site/index.j2", menues=payload, str_dias=payload_dias)


@core_bp.route("/admin", methods=["GET"])
@roles_required("admin")
def admin():
    return render_template("seleccion.html")


@core_bp.route("/aiuda", methods=["GET"])
def ayuda():
    return render_template("core/ayuda.html")


@core_bp.route("/configuracion", methods=["GET"])
@login_required
def configuracion():
    return render_template("core/configuracion.html")


def obtiene_menues(dia):

    if dia:
        try:
            fecha = datetime.strptime(dia, "%Y-%m-%d").date()
        except ValueError:
            return None
    else:
        fecha = date.today()

    menu_hoy = MenuDiario.query.filter(
        or_(MenuDiario.dia == fecha, MenuDiario.es_permanente == True),
        and_(MenuDiario.activo == True),
    ).all()
    return menu_hoy


@core_bp.route("/consulta/<dia>")
@login_required
def consulta(dia):
    menues = obtiene_menues(dia)
    if not menues:
        abort(404)

    return render_template("casino/form_menu.html", menues=menues, dia=dia)
