from decimal import Decimal
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from ..database import db
from ..model import Apoderado, Settings, Alumno, Abono, Payment
from .controller import ApoderadoController
from slugify import slugify
from flask_security import current_user, roles_required, roles_accepted, login_required  # type: ignore

# from flask_merchants.core import PaymentStatus

apoderado_bp = Blueprint("apoderado_cliente", __name__)
apoderado_controller = ApoderadoController()


@apoderado_bp.route("/", methods=["GET"])
@roles_accepted("apoderado", "admin")
def index():
    apoderado = None
    if current_user.has_role("apoderado"):
        apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one_or_none()
    if not apoderado and current_user.has_role("admin"):
        return redirect(url_for(".wizp1"))
    if not apoderado and not current_user.has_role("admin"):
        return redirect(url_for("core.index"))
    if not apoderado and current_user.has_role("apoderado"):
        return redirect(url_for(".wizp1"))
    return render_template("apoderado/dashboard.html", apoderado=apoderado)


@apoderado_bp.route("/wizard", methods=["GET"])
@apoderado_bp.route("/wizard/1", methods=["GET", "POST"])
@login_required
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
@login_required
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
@login_required
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
        limite_notificaciones = request.form.get("monto_semanal", 1500)
        apoderado.comprobantes_transferencia = bool(notificacion_comprobante)
        apoderado.notificacion_compra = bool(notificacion_compra)
        apoderado.informe_semanal = bool(informe_semanal)
        apoderado.tag_compartido = bool(tag_compartido)
        apoderado.copia_notificaciones = correo_alternativo
        apoderado.maximo_diario = int(monto_diario)
        apoderado.maximo_semanal = int(monto_semanal)
        apoderado.limite_notificaciones = int(limite_notificaciones)
        apoderado.saldo_cuenta = 1

        for alumno in apoderado.alumnos:
            alumno.maximo_diario = apoderado.maximo_diario
            alumno.maximo_semanal = apoderado.maximo_semanal

        # wizard_completado = Settings()
        # wizard_completado.user_id = current_user.id
        # wizard_completado.slug = "wizard"
        # wizard_completado.value = {"status": "ok"}
        # db.session.add(wizard_completado)

        db.session.commit()
        return redirect(url_for(".wizp4"))

    return render_template("apoderado/wizard-paso3.html")


@apoderado_bp.route("/wizard/4", methods=["GET"])
@login_required
def wizp4():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    ## Notificar a Admins
    correo = render_template("core/emails/nuevo_apoderado.html", apoderado=apoderado)

    return render_template("apoderado/wizard-paso4.html", apoderado=apoderado)


@apoderado_bp.route("/abono", methods=["POST"])
@roles_accepted("apoderado", "admin")
def abono():
    monto = request.form["monto"]
    forma_pago = request.form["forma-de-pago"]
    abono = Abono()
    abono.monto = Decimal(monto)
    abono.apoderado = current_user.apoderado
    abono.descripcion = "Abono Web"
    abono.forma_pago = forma_pago

    db.session.add(abono)
    db.session.commit()

    # pago = Payment()
    # pago.merchants_token = abono.codigo
    # pago.amount = abono.monto
    # pago.currency = "CLP"
    # pago.integration_slug = abono.forma_pago

    # db.session.add(pago)
    # db.session.commit()

    # Para evitar el re-POST, el procesamiento se hace en el detalle, antes de mostrar algo
    return redirect(f"abono-detalle/{abono.codigo}")


@apoderado_bp.route("/abono-detalle/<string:codigo>", methods=["GET"])
def abono_detalle(codigo):
    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = db.session.execute(db.select(Payment).filter_by(session_id=codigo)).scalar_one_or_none()
    pago_process = None

    # if (
    #     pago
    #     and abono
    #     and pago.integration.slug == abono.forma_pago
    #     and pago.amount == abono.monto
    #     and pago.status == PaymentStatus.created
    # ):
    #     pago_process = pago.process()

    #     if "transaction" in pago_process:
    #         pago.status = PaymentStatus.processing

    #         db.session.commit()
    #     if "url" in pago_process:
    #         return redirect(pago_process["url"])

    return render_template("apoderado/detalle-abono.html", abono=abono, pago=pago)


@apoderado_bp.route("/menu-casino", methods=["GET"])
def menu_casino():
    return render_template("apoderado/menu-casino.html")


@apoderado_bp.route("/almuerzos", methods=["GET"])
def almuerzos():
    return render_template("apoderado/abonos.html")


@apoderado_bp.route("/kiosko", methods=["GET"])
def kiosko():
    return render_template("apoderado/kiosko.html")


@apoderado_bp.route("/ficha-alumno/<int:id>", methods=["GET"])
def ficha(id):
    alumno = db.session.execute(db.select(Alumno).filter_by(apoderado=current_user.apoderado, id=id)).scalar_one()
    return render_template("apoderado/ficha.html", alumno=alumno)


@apoderado_bp.route("/abonos", methods=["GET"])
def abonos():
    return render_template("apoderado/abonos.html")
