from celery import shared_task
from flask import current_app, render_template, url_for
from flask_mailman import EmailMultiAlternatives
from flask_security.mail_util import MailUtil

from .extensions import mail


def _get_display_code(pago) -> str:
    """Extrae el código de display del pago, si existe."""
    if pago is None:
        return ""
    return (pago.metadata_json or {}).get("display_code", "")


def _get_from_email() -> str:
    """Retorna el remitente configurado en MAIL_USERNAME o el valor por defecto."""
    return current_app.config.get(
        "MAIL_USERNAME",
        current_app.config.get("MAIL_DEFAULT_SENDER", "no-reply@sabormirandiano.cl"),
    )


class MyMailUtil(MailUtil):
    def send_mail(self, template, subject, recipient, sender, body, html, **kwargs):
        kwargs["user"] = kwargs["user"].__dict__
        send_flask_mail.delay(
            subject=subject,
            from_email=sender,
            to=[recipient],
            body=body,
            html=html,
        )  # type: ignore


@shared_task(bind=True, ignore_result=False)
def send_flask_mail(*args, **kwargs):
    with current_app.app_context():
        with mail.get_connection() as connection:
            html = kwargs.pop("html", None)
            msg = EmailMultiAlternatives(**kwargs, connection=connection)
            if html:
                msg.attach_alternative(html, "text/html")
                msg.send()


@shared_task(bind=True, ignore_result=False)
def send_comprobante_abono(self, abono_id: int):
    """Envía comprobante de abono al apoderado."""
    with current_app.app_context():
        from .database import db
        from .model import Abono, Payment

        abono = db.session.get(Abono, abono_id)
        if not abono:
            return
        pago = db.session.execute(db.select(Payment).filter_by(session_id=abono.codigo)).scalar_one_or_none()
        apoderado = abono.apoderado
        email = apoderado.usuario.email
        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono.codigo, _external=True)
        subject = f"Comprobante de abono #{abono.codigo[:8].upper()}"
        body = (
            f"Hola {apoderado.nombre},\n\n"
            f"Tu abono ha sido procesado exitosamente.\n\n"
            f"Código: {abono.codigo[:8].upper()}\n"
            f"Monto: ${int(abono.monto):,}\n"
            f"Forma de pago: {abono.forma_pago}\n"
        )
        if display_code:
            body += f"Código de pago: {display_code}\n"
        body += f"\nNuevo saldo en cuenta: ${int(apoderado.saldo_cuenta or 0):,}\n\nSaludos,\nCafetería SaborMirandiano"
        html = render_template(
            "core/emails/nuevo_abono_apoderado.html",
            nombre_apoderado=apoderado.nombre,
            monto=abono.monto,
            forma_pago=abono.forma_pago,
            codigo=abono.codigo[:8].upper(),
            display_code=display_code,
            saldo_cuenta=apoderado.saldo_cuenta or 0,
            abono_url=abono_url,
        )
        from_email = _get_from_email()
        with mail.get_connection() as connection:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=body,
                from_email=from_email,
                to=[email],
                connection=connection,
            )
            msg.attach_alternative(html, "text/html")
            msg.send()


@shared_task(bind=True, ignore_result=False)
def send_notificacion_admin_abono(self, abono_id: int):
    """Notifica a los administradores sobre un abono aprobado."""
    with current_app.app_context():
        from .database import db
        from .model import Abono, Payment, Role, User

        abono = db.session.get(Abono, abono_id)
        if not abono:
            return
        pago = db.session.execute(db.select(Payment).filter_by(session_id=abono.codigo)).scalar_one_or_none()
        apoderado = abono.apoderado

        admin_role = db.session.execute(db.select(Role).filter_by(name="admin")).scalar_one_or_none()
        if not admin_role:
            return
        admin_emails = [u.email for u in admin_role.users if u.email]
        if not admin_emails:
            return

        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono.codigo, _external=True)
        subject = f"Abono aprobado – {apoderado.nombre} ${int(abono.monto):,}"
        body = (
            f"Se aprobó un abono en la cafetería.\n\n"
            f"Apoderado: {apoderado.nombre} ({apoderado.usuario.email})\n"
            f"Código abono: {abono.codigo}\n"
            f"Monto: ${int(abono.monto):,}\n"
            f"Forma de pago: {abono.forma_pago}\n"
            f"Descripción: {abono.descripcion}\n"
        )
        if pago:
            body += (
                f"\nDetalle del pago:\n"
                f"  Proveedor: {pago.provider}\n"
                f"  Estado: {pago.state}\n"
                f"  Código de pago: {display_code}\n"
                f"  Session ID: {pago.session_id}\n"
            )
        body += f"\nSaldo actual del apoderado: ${int(apoderado.saldo_cuenta or 0):,}"
        html = render_template(
            "core/emails/nuevo_abono_admin.html",
            nombre_apoderado=apoderado.nombre,
            email_apoderado=apoderado.usuario.email,
            monto=abono.monto,
            forma_pago=abono.forma_pago,
            codigo=abono.codigo,
            descripcion=abono.descripcion,
            saldo_cuenta=apoderado.saldo_cuenta or 0,
            pago_proveedor=pago.provider if pago else None,
            pago_estado=pago.state if pago else None,
            display_code=display_code,
            session_id=pago.session_id if pago else None,
            abono_url=abono_url,
        )
        from_email = _get_from_email()
        with mail.get_connection() as connection:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=body,
                from_email=from_email,
                to=admin_emails,
                connection=connection,
            )
            msg.attach_alternative(html, "text/html")
            msg.send()
