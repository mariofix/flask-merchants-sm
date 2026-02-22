from flask import Blueprint, abort, redirect, render_template, request, url_for
from .model import MenuDiario
from .database import db
from datetime import date, datetime
from collections import OrderedDict
from sqlalchemy import and_, or_, select
from flask_login import login_required, current_user
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


@core_bp.route("/configuracion", methods=["GET", "POST"])
@login_required
def configuracion():
    from .model import Apoderado
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one_or_none()

    if request.method == "POST":
        if apoderado:
            apoderado.nombre = request.form.get("nombre", apoderado.nombre)
            apoderado.comprobantes_transferencia = bool(request.form.get("comprobantes_transferencia"))
            apoderado.notificacion_compra = bool(request.form.get("notificacion_compra"))
            apoderado.informe_semanal = bool(request.form.get("informe_semanal"))
            apoderado.copia_notificaciones = request.form.get("copia_notificaciones", apoderado.copia_notificaciones)
            monto_diario = request.form.get("maximo_diario")
            if monto_diario:
                try:
                    apoderado.maximo_diario = int(monto_diario)
                except ValueError:
                    pass
            monto_semanal = request.form.get("maximo_semanal")
            if monto_semanal:
                try:
                    apoderado.maximo_semanal = int(monto_semanal)
                except ValueError:
                    pass
        phone = request.form.get("phone")
        if phone:
            current_user.username = phone
        db.session.commit()
        return redirect(url_for("core.configuracion"))

    return render_template("core/configuracion.html", apoderado=apoderado, current_user=current_user)


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
