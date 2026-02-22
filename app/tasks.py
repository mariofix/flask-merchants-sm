from celery import shared_task
from flask import current_app, render_template, url_for
from flask_mailman import EmailMultiAlternatives
from flask_security.mail_util import MailUtil
from flask_merchants import merchants_audit
import re

from .extensions import mail


def _get_display_code(pago) -> str:
    """Extrae el código de display del pago, si existe."""
    if pago is None:
        return ""
    return (pago.metadata_json or {}).get("display_code", "")


def _parse_copia_emails(raw: str) -> list[str]:
    """Parsea uno o varios correos separados por coma o punto y coma."""
    emails = [e.strip() for e in re.split(r"[,;]", raw) if e.strip()]
    return emails


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
                merchants_audit.info(
                    "email_sent: from=%r to=%r subject=%r",
                    kwargs.get("from_email"),
                    kwargs.get("to"),
                    kwargs.get("subject"),
                )


@shared_task(bind=True, ignore_result=False)
def send_comprobante_abono(self, abono_info: dict):
    """Envía comprobante de abono al apoderado."""
    with current_app.app_context():
        from .database import db
        from .model import Payment

        pago = db.session.execute(db.select(Payment).filter_by(session_id=abono_info["codigo"])).scalar_one_or_none()
        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono_info["codigo"], _external=True)
        subject = f"Comprobante de abono #{abono_info['codigo'][:8].upper()}"
        body = (
            f"Hola {abono_info['apoderado_nombre']},\n\n"
            f"Tu abono ha sido procesado exitosamente.\n\n"
            f"Código: {abono_info['codigo'][:8].upper()}\n"
            f"Monto: ${abono_info['monto']:,}\n"
            f"Forma de pago: {abono_info['forma_pago']}\n"
        )
        if display_code:
            body += f"Código de pago: {display_code}\n"
        body += f"\nNuevo saldo en cuenta: ${abono_info['saldo_cuenta']:,}\n\nSaludos,\nCafetería SaborMirandiano"
        html = render_template(
            "core/emails/nuevo_abono_apoderado.html",
            nombre_apoderado=abono_info["apoderado_nombre"],
            monto=abono_info["monto"],
            forma_pago=abono_info["forma_pago"],
            codigo=abono_info["codigo"][:8].upper(),
            display_code=display_code,
            saldo_cuenta=abono_info["saldo_cuenta"],
            abono_url=abono_url,
        )
        from_email = _get_from_email()
        with mail.get_connection() as connection:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=body,
                from_email=from_email,
                to=[abono_info["apoderado_email"]],
                connection=connection,
            )
            msg.attach_alternative(html, "text/html")
            msg.send()
            merchants_audit.info(
                "email_sent: from=%r to=%r subject=%r",
                from_email,
                [abono_info["apoderado_email"]],
                subject,
            )


@shared_task(bind=True, ignore_result=False)
def send_notificacion_admin_abono(self, abono_info: dict):
    """Notifica a los administradores sobre un abono aprobado."""
    with current_app.app_context():
        from .database import db
        from .model import Payment, Role

        pago = db.session.execute(db.select(Payment).filter_by(session_id=abono_info["codigo"])).scalar_one_or_none()

        admin_role = db.session.execute(db.select(Role).filter_by(name="admin")).scalar_one_or_none()
        if not admin_role:
            return
        admin_emails = [u.email for u in admin_role.users if u.email]
        if not admin_emails:
            return

        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono_info["codigo"], _external=True)
        subject = f"[admin] Abono aprobado – {abono_info['apoderado_nombre']} ${abono_info['monto']:,}"
        body = (
            f"Se aprobó un abono en la cafetería.\n\n"
            f"Apoderado: {abono_info['apoderado_nombre']} ({abono_info['apoderado_email']})\n"
            f"Código abono: {abono_info['codigo']}\n"
            f"Monto: ${abono_info['monto']:,}\n"
            f"Forma de pago: {abono_info['forma_pago']}\n"
            f"Descripción: {abono_info['descripcion']}\n"
        )
        if pago:
            body += (
                f"\nDetalle del pago:\n"
                f"  Proveedor: {pago.provider}\n"
                f"  Estado: {pago.state}\n"
                f"  Código de pago: {display_code}\n"
                f"  Session ID: {pago.session_id}\n"
            )
        body += f"\nSaldo actual del apoderado: ${abono_info['saldo_cuenta']:,}"
        html = render_template(
            "core/emails/nuevo_abono_admin.html",
            nombre_apoderado=abono_info["apoderado_nombre"],
            email_apoderado=abono_info["apoderado_email"],
            monto=abono_info["monto"],
            forma_pago=abono_info["forma_pago"],
            codigo=abono_info["codigo"],
            descripcion=abono_info["descripcion"],
            saldo_cuenta=abono_info["saldo_cuenta"],
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
            merchants_audit.info(
                "email_sent: from=%r to=%r subject=%r",
                from_email,
                admin_emails,
                subject,
            )


@shared_task(bind=True, ignore_result=False)
def send_copia_notificaciones_abono(self, abono_info: dict):
    """Envía copia del comprobante de abono a los correos de copia_notificaciones."""
    copia_raw = abono_info.get("copia_notificaciones") or ""
    copia_emails = _parse_copia_emails(copia_raw)
    if not copia_emails:
        return
    with current_app.app_context():
        from .database import db
        from .model import Payment

        pago = db.session.execute(db.select(Payment).filter_by(session_id=abono_info["codigo"])).scalar_one_or_none()
        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono_info["codigo"], _external=True)
        subject = f"Comprobante de abono #{abono_info['codigo'][:8].upper()}"
        body = (
            f"Hola {abono_info['apoderado_nombre']},\n\n"
            f"Tu abono ha sido procesado exitosamente.\n\n"
            f"Código: {abono_info['codigo'][:8].upper()}\n"
            f"Monto: ${abono_info['monto']:,}\n"
            f"Forma de pago: {abono_info['forma_pago']}\n"
        )
        if display_code:
            body += f"Código de pago: {display_code}\n"
        body += f"\nNuevo saldo en cuenta: ${abono_info['saldo_cuenta']:,}\n\nSaludos,\nCafetería SaborMirandiano"
        html = render_template(
            "core/emails/nuevo_abono_apoderado.html",
            nombre_apoderado=abono_info["apoderado_nombre"],
            monto=abono_info["monto"],
            forma_pago=abono_info["forma_pago"],
            codigo=abono_info["codigo"][:8].upper(),
            display_code=display_code,
            saldo_cuenta=abono_info["saldo_cuenta"],
            abono_url=abono_url,
        )
        from_email = _get_from_email()
        with mail.get_connection() as connection:
            for email in copia_emails:
                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=body,
                    from_email=from_email,
                    to=[email],
                    connection=connection,
                )
                msg.attach_alternative(html, "text/html")
                msg.send()
                merchants_audit.info(
                    "email_sent: from=%r to=%r subject=%r",
                    from_email,
                    [email],
                    subject,
                )


@shared_task(bind=True, ignore_result=False)
def send_notificacion_abono_creado(self, abono_info: dict):
    """Notifica al apoderado que su abono fue recibido y le entrega el código de pago.
    También notifica a los administradores que hay un abono pendiente con el código generado."""
    with current_app.app_context():
        from .database import db
        from .model import Payment, Role

        pago = db.session.execute(db.select(Payment).filter_by(session_id=abono_info["codigo"])).scalar_one_or_none()
        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono_info["codigo"], _external=True)
        from_email = _get_from_email()

        # --- Email al apoderado ---
        subject_apoderado = f"Solicitud de abono recibida – ${abono_info['monto']:,}"
        body_apoderado = (
            f"Hola {abono_info['apoderado_nombre']},\n\n"
            f"Tu solicitud de abono ha sido recibida.\n\n"
            f"Código: {abono_info['codigo'][:8].upper()}\n"
            f"Monto: ${abono_info['monto']:,}\n"
            f"Forma de pago: {abono_info['forma_pago']}\n"
        )
        if display_code:
            body_apoderado += f"\nPresenta este código en la cafetería del colegio: {display_code}\n"
        body_apoderado += f"\nVer detalle: {abono_url}\n\nSaludos,\nCafetería SaborMirandiano"
        html_apoderado = render_template(
            "core/emails/nuevo_abono_apoderado.html",
            nombre_apoderado=abono_info["apoderado_nombre"],
            monto=abono_info["monto"],
            forma_pago=abono_info["forma_pago"],
            codigo=abono_info["codigo"][:8].upper(),
            display_code=display_code,
            saldo_cuenta=abono_info.get("saldo_cuenta", 0),
            abono_url=abono_url,
        )
        with mail.get_connection() as connection:
            msg = EmailMultiAlternatives(
                subject=subject_apoderado,
                body=body_apoderado,
                from_email=from_email,
                to=[abono_info["apoderado_email"]],
                connection=connection,
            )
            msg.attach_alternative(html_apoderado, "text/html")
            msg.send()
            merchants_audit.info(
                "email_sent: from=%r to=%r subject=%r",
                from_email,
                [abono_info["apoderado_email"]],
                subject_apoderado,
            )

        # --- Email a los administradores (código generado, abono pendiente) ---
        admin_role = db.session.execute(db.select(Role).filter_by(name="admin")).scalar_one_or_none()
        admin_emails = [u.email for u in admin_role.users if u.email] if admin_role else []
        if admin_emails:
            subject_admin = f"[admin] Nuevo abono pendiente – {abono_info['apoderado_nombre']} ${abono_info['monto']:,}"
            body_admin = (
                f"Se ha generado un código de abono en la cafetería.\n\n"
                f"Apoderado: {abono_info['apoderado_nombre']} ({abono_info['apoderado_email']})\n"
                f"Código abono: {abono_info['codigo']}\n"
                f"Monto: ${abono_info['monto']:,}\n"
                f"Forma de pago: {abono_info['forma_pago']}\n"
            )
            if display_code:
                body_admin += f"Código de pago: {display_code}\n"
            body_admin += f"\nVer detalle: {abono_url}"
            html_admin = render_template(
                "core/emails/nuevo_abono_admin.html",
                nombre_apoderado=abono_info["apoderado_nombre"],
                email_apoderado=abono_info["apoderado_email"],
                monto=abono_info["monto"],
                forma_pago=abono_info["forma_pago"],
                codigo=abono_info["codigo"],
                descripcion=abono_info.get("descripcion"),
                saldo_cuenta=abono_info.get("saldo_cuenta", 0),
                pago_proveedor=pago.provider if pago else None,
                pago_estado=pago.state if pago else None,
                display_code=display_code,
                session_id=pago.session_id if pago else None,
                abono_url=abono_url,
            )
            with mail.get_connection() as connection:
                msg = EmailMultiAlternatives(
                    subject=subject_admin,
                    body=body_admin,
                    from_email=from_email,
                    to=admin_emails,
                    connection=connection,
                )
                msg.attach_alternative(html_admin, "text/html")
                msg.send()
                merchants_audit.info(
                    "email_sent: from=%r to=%r subject=%r",
                    from_email,
                    admin_emails,
                    subject_admin,
                )


@shared_task(bind=True, ignore_result=False)
def send_notificacion_admin_nuevo_apoderado(self, apoderado_info: dict):
    """Notifica a los administradores sobre un nuevo apoderado registrado."""
    with current_app.app_context():
        from .database import db
        from .model import Role

        admin_role = db.session.execute(db.select(Role).filter_by(name="admin")).scalar_one_or_none()
        if not admin_role:
            return
        admin_emails = [u.email for u in admin_role.users if u.email]
        if not admin_emails:
            return

        subject = f"[admin] Nuevo apoderado registrado – {apoderado_info['nombre_apoderado']}"
        body = (
            f"Se ha registrado un nuevo apoderado en la plataforma.\n\n"
            f"Nombre: {apoderado_info['nombre_apoderado']}\n"
            f"Correo: {apoderado_info['email_apoderado']}\n"
            f"Alumnos registrados: {len(apoderado_info.get('alumnos', []))}\n"
        )
        for alumno in apoderado_info.get("alumnos", []):
            body += f"  - {alumno['nombre']} ({alumno['curso']})\n"

        html = render_template(
            "core/emails/nuevo_apoderado.html",
            nombre_apoderado=apoderado_info["nombre_apoderado"],
            email_apoderado=apoderado_info["email_apoderado"],
            alumnos=apoderado_info.get("alumnos", []),
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
            merchants_audit.info(
                "email_sent: from=%r to=%r subject=%r",
                from_email,
                admin_emails,
                subject,
            )
