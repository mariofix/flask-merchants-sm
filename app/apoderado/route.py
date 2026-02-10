from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_security.forms import RegisterFormV2
from flask_security.registerable import register_user

from ..database import db
from ..model import Apoderado
from .controller import ApoderadoController

apoderado_bp = Blueprint("apoderado_cliente", __name__)
apoderado_controller = ApoderadoController()


@apoderado_bp.route("/", methods=["GET"])
def index():
    return render_template("apoderado/dashboard.html")


@apoderado_bp.route("/register_test", methods=["GET"])
def reg_test():
    nombre = "nombre apoderado"
    correo = "mario+apoderado4@fonotarot.com"
    telefono = "56987654324"
    alumnos = 3
    with current_app.app_context():
        security = current_app.extensions["security"]
        if security.datastore.find_user(email=correo):
            flash("Correo Existe", "error")
            print("Correo existe")
            return render_template("apoderado/wizard-paso1.html")

        if security.datastore.find_user(username=telefono):
            flash("Telefono Existe", "error")
            print("telefono existe")
            return render_template("apoderado/wizard-paso1.html")
        formulario_registro = RegisterFormV2(
            username=telefono, email=correo, password="__NOT_USED__", password_confirm="__NOT_USED__"
        )
        usuario = register_user(formulario_registro)
        print(f"{usuario =}")
        apoderado = Apoderado()
        apoderado.nombre = nombre
        apoderado.usuario_id = usuario.id
        db.session.add(apoderado)
        db.session.commit()
        print(apoderado)

    return render_template("apoderado/wizard-paso1.html")


@apoderado_bp.route("/wizard", methods=["GET"])
@apoderado_bp.route("/wizard/1", methods=["GET", "POST"])
def wizp1():
    if request.method == "POST":
        nombre = request.form["apoderado_nombre"]
        correo = request.form["apoderado_correo"]
        telefono = request.form["apoderado_telefono"]
        alumnos = request.form["alumnos"]
        with current_app.app_context():
            security = current_app.extensions["security"]
            if security.datastore.find_user(email=correo):
                flash("Correo Existe", "error")
                return render_template("apoderado/wizard-paso1.html")

            if security.datastore.find_user(username=telefono):
                flash("Telefono Existe", "error")
                return render_template("apoderado/wizard-paso1.html")
            formulario_registro = RegisterFormV2(
                username=telefono, email=correo, password="__NOT_USED__", password_confirm="__NOT_USED__"
            )
            usuario = register_user(formulario_registro)
            apoderado = Apoderado()
            apoderado.nombre = nombre
            apoderado.usuario_id = usuario.id
            db.session.add(apoderado)
            db.session.commit()
            return redirect(url_for(".wizp2"))

    return render_template("apoderado/wizard-paso1.html")


@apoderado_bp.route("/wizard/2", methods=["GET", "POST"])
def wizp2():
    return render_template("apoderado/wizard-paso2.html")


@apoderado_bp.route("/wizard/3", methods=["GET", "POST"])
def wizp3():
    return render_template("apoderado/wizard-paso3.html")


@apoderado_bp.route("/wizard/4", methods=["GET", "POST"])
def wizp4():
    return render_template("apoderado/wizard-paso4.html")


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
