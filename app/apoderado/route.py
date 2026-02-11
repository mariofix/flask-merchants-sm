from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from ..database import db
from ..model import Apoderado, Settings, Alumno
from .controller import ApoderadoController
from slugify import slugify


apoderado_bp = Blueprint("apoderado_cliente", __name__)
apoderado_controller = ApoderadoController()


@apoderado_bp.route("/", methods=["GET"])
def index():
    return render_template("apoderado/dashboard.html")


@apoderado_bp.route("/wizard", methods=["GET"])
@apoderado_bp.route("/wizard/1", methods=["GET", "POST"])
def wizp1():

    if request.method == "POST":
        nombre = request.form["apoderado_nombre"]
        alumnos = request.form["alumnos"]

        apoderado = Apoderado()
        apoderado.nombre = nombre
        apoderado.alumnos_registro = int(alumnos)
        apoderado.usuario_id = current_user.id
        db.session.add(apoderado)

        uds = current_app.extensions["user_datastore"]
        uds.add_role_to_user(current_user, "apoderado")

        db.session.commit()

        return redirect(url_for(".wizp2"))

    return render_template("apoderado/wizard-paso1.html")


@apoderado_bp.route("/wizard/2", methods=["GET", "POST"])
def wizp2():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    cursos = db.session.execute(db.select(Settings).filter_by(slug="cursos")).scalar_one()
    if request.method == "POST":
        for num in range(1, apoderado.alumnos_registro + 1):
            nuevo_arr = {
                "nombre": request.form[f"nombre_alumno_{num}"],
                "curso": request.form[f"curso_alumno_{num}"],
                "edad": request.form[f"edad_alumno_{num}"],
            }
            nuevo = Alumno()
            nuevo.slug = slugify(f"{nuevo_arr.get("nombre", "")} {nuevo_arr.get("edad", "")}")
            nuevo.nombre = nuevo_arr.get("nombre", "")
            nuevo.curso = nuevo_arr.get("curso", "")
            nuevo.apoderado = apoderado
            db.session.add(nuevo)
            del nuevo
        db.session.commit()
        return redirect(url_for(".wizp3"))

    return render_template("apoderado/wizard-paso2.html", apoderado=apoderado, cursos=cursos.value)


@apoderado_bp.route("/wizard/3", methods=["GET", "POST"])
def wizp3():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    if request.method == "POST":
        notificacion_compra = request.form.get("notificacion_compra", False)
        notificacion_comprobante = request.form.get("notificacion_comprobante", False)
        informe_semanal = request.form.get("informe_semanal", False)
        tag_compartido = request.form.get("tag_compartido", False)
        correo_alternativo = request.form.get("correo_alternativo", False)
        monto_diario = request.form.get("monto_diario", False)
        monto_semanal = request.form.get("monto_semanal", False)
        apoderado.comprobantes_transferencia = bool(notificacion_comprobante)
        apoderado.notificacion_compra = bool(notificacion_compra)
        apoderado.informe_semanal = bool(informe_semanal)
        apoderado.tag_compartido = bool(tag_compartido)
        apoderado.copia_notificaciones = correo_alternativo
        apoderado.maximo_diario = int(monto_diario)
        apoderado.maximo_semanal = int(monto_semanal)
        db.session.commit()
        return redirect(url_for(".wizp4"))

    return render_template("apoderado/wizard-paso3.html")


@apoderado_bp.route("/wizard/4", methods=["GET"])
def wizp4():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    ## Notificar a Admins

    return render_template("apoderado/wizard-paso4.html", apoderado=apoderado)


@apoderado_bp.route("/abonar", methods=["GET", "POST"])
def abonar():
    return render_template("apoderado/abono.html")


@apoderado_bp.route("/menu-casino", methods=["GET"])
def menu_casino():
    return render_template("apoderado/menu-casino.html")


@apoderado_bp.route("/kiosko", methods=["GET"])
def kiosko():
    return render_template("apoderado/kiosko.html")


@apoderado_bp.route("/ficha-alumno/<int:id>", methods=["GET"])
def ficha(id):
    return render_template("apoderado/ficha.html")


@apoderado_bp.route("/abonos", methods=["GET"])
def abonos():
    return render_template("apoderado/abonos.html")
