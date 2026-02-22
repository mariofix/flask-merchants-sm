from decimal import Decimal, InvalidOperation
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from ..database import db
from ..model import Apoderado, Settings, Alumno, Abono, Payment
from .controller import ApoderadoController
from slugify import slugify
from flask_security import current_user, roles_required, roles_accepted, login_required  # type: ignore

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
        apoderado.limite_notificacion = int(limite_notificaciones)
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

        from ..tasks import send_notificacion_admin_nuevo_apoderado
        from flask_merchants import merchants_audit
        send_notificacion_admin_nuevo_apoderado.delay({
            "nombre_apoderado": apoderado.nombre,
            "email_apoderado": apoderado.usuario.email,
            "alumnos": [{"nombre": a.nombre, "curso": a.curso} for a in apoderado.alumnos],
        })
        merchants_audit.info(
            "nuevo_apoderado_creado: id=%s nombre=%r email=%r alumnos=%d",
            apoderado.id,
            apoderado.nombre,
            apoderado.usuario.email,
            len(apoderado.alumnos),
        )
        merchants_audit.info(
            "nuevo_apoderado_notificado: id=%s nombre=%r email=%r",
            apoderado.id,
            apoderado.nombre,
            apoderado.usuario.email,
        )

        return redirect(url_for(".wizp4"))

    return render_template("apoderado/wizard-paso3.html")


@apoderado_bp.route("/wizard/4", methods=["GET"])
@login_required
def wizp4():
    apoderado = db.session.execute(db.select(Apoderado).filter_by(usuario=current_user)).scalar_one()
    ## Notificar a Admins
    correo = render_template("core/emails/nuevo_apoderado.html", apoderado=apoderado)

    return render_template("apoderado/wizard-paso4.html", apoderado=apoderado)


@apoderado_bp.route("/abono", methods=["GET"])
@roles_accepted("apoderado", "admin")
def abono_form():
    return render_template("apoderado/abono.html")


@apoderado_bp.route("/abono", methods=["POST"])
@roles_accepted("apoderado", "admin")
def abono():
    monto = request.form.get("monto", "").strip()
    forma_pago = request.form.get("forma-de-pago", "")
    try:
        monto_decimal = Decimal(monto)
    except InvalidOperation:
        if not monto:
            flash("Por favor ingrese un monto.", "danger")
        else:
            flash("El monto ingresado no es válido. Por favor ingrese un valor numérico.", "danger")
        return redirect(url_for("apoderado_cliente.abono_form"))
    nuevo_abono = Abono()
    nuevo_abono.monto = monto_decimal
    nuevo_abono.apoderado = current_user.apoderado
    nuevo_abono.descripcion = "Abono Web"
    nuevo_abono.forma_pago = forma_pago

    db.session.add(nuevo_abono)
    db.session.commit()

    if forma_pago == "cafeteria":
        from ..extensions import flask_merchants

        session = flask_merchants.get_client("cafeteria").payments.create_checkout(
            amount=nuevo_abono.monto,
            currency="CLP",
            success_url=url_for(
                "apoderado_cliente.abono_detalle", codigo=nuevo_abono.codigo, _external=True
            ),
            cancel_url=url_for("apoderado_cliente.index", _external=True),
            metadata={
                "abono_codigo": nuevo_abono.codigo,
                "apoderado_id": str(nuevo_abono.apoderado.id),
            },
        )
        flask_merchants.save_session(
            session,
            model_class=Payment,
            request_payload={
                "abono_codigo": nuevo_abono.codigo,
                "monto": str(nuevo_abono.monto),
                "currency": "CLP",
                "apoderado_id": str(nuevo_abono.apoderado.id),
                "forma_pago": forma_pago,
            },
        )
        # Marcar como "processing" – esperando pago presencial
        flask_merchants.update_state(nuevo_abono.codigo, "processing")

        from ..tasks import send_notificacion_abono_creado
        send_notificacion_abono_creado.delay(abono_info={
            "codigo": nuevo_abono.codigo,
            "monto": int(nuevo_abono.monto),
            "forma_pago": nuevo_abono.forma_pago,
            "descripcion": nuevo_abono.descripcion,
            "apoderado_nombre": nuevo_abono.apoderado.nombre,
            "apoderado_email": nuevo_abono.apoderado.usuario.email,
            "saldo_cuenta": nuevo_abono.apoderado.saldo_cuenta or 0,
        })

    return redirect(url_for("apoderado_cliente.abono_detalle", codigo=nuevo_abono.codigo))


@apoderado_bp.route("/abono-detalle/<string:codigo>", methods=["GET"])
def abono_detalle(codigo):
    abono = db.session.execute(db.select(Abono).filter_by(codigo=codigo)).scalar_one_or_none()
    pago = db.session.execute(db.select(Payment).filter_by(session_id=codigo)).scalar_one_or_none()
    display_code = (pago.metadata_json or {}).get("display_code", "") if pago else ""
    return render_template("apoderado/detalle-abono.html", abono=abono, pago=pago, display_code=display_code)


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
