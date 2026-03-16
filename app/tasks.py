import logging
import re

from daleks.contrib.client import DaleksClient
from flask import current_app, render_template, url_for
from flask_merchants import merchants_audit


def _get_display_code(pago) -> str:
    """Extrae el código de display del pago, si existe.

    Checks ``response_payload`` first (provider raw response), then falls
    back to ``metadata_json`` for backward compatibility with older records.
    """
    if pago is None:
        return ""
    code = (pago.response_payload or {}).get("display_code", "")
    if not code:
        code = (pago.metadata_json or {}).get("display_code", "")
    return code


def _parse_copia_emails(raw: str) -> list[str]:
    """Parsea uno o varios correos separados por coma o punto y coma."""
    emails = [e.strip() for e in re.split(r"[,;]", raw) if e.strip()]
    return emails


def _get_from_email() -> str:
    """Retorna el remitente configurado en DALEKS_FROM_EMAIL o el valor por defecto."""
    return current_app.config.get(
        "DALEKS_FROM_EMAIL",
        "no-reply@sabormirandiano.cl",
    )


def _send_daleks_email(
    from_address: str,
    to: str | list[str],
    subject: str,
    text_body: str | None = None,
    html_body: str | None = None,
) -> None:
    """Envía un email a través del servicio Daleks y registra en el log de auditoría."""
    _log = logging.getLogger("sm.app")
    cfg = current_app.config
    base_url: str = cfg.get("DALEKS_URL", "http://zvn-lin2.local:2525")
    timeout: int = int(cfg.get("DALEKS_TIMEOUT", 10))
    smtp_account: str | None = cfg.get("DALEKS_SMTP_ACCOUNT") or None
    to_list = [to] if isinstance(to, str) else to
    try:
        client = DaleksClient(base_url=base_url, timeout=timeout, smtp_account=smtp_account)
        with client:
            client.send_email(
                from_address=from_address,
                to=to_list,
                subject=subject,
                text_body=text_body or None,
                html_body=html_body or None,
            )
        merchants_audit.info(
            "email_sent: from=%r to=%r subject=%r",
            from_address,
            to_list,
            subject,
        )
    except Exception as exc:
        _log.error("daleks_email_failed: to=%r subject=%r error=%r", to_list, subject, exc)


def send_webhook_notification_email(webhook_info: dict):
    """Send webhook notification email to admin users.

    ``webhook_info`` is the dict produced by
    :meth:`FlaskMerchants._webhook_notification_handler` and contains
    ``subject``, ``body``, ``to``, ``provider``, ``transaction``,
    ``headers_json``, and ``body_json``.
    """
    with current_app.app_context():
        from_email = _get_from_email()
        html = render_template(
            "core/emails/webhook_notification.html",
            provider=webhook_info["provider"],
            transaction=webhook_info["transaction"],
            headers_json=webhook_info["headers_json"],
            body_json=webhook_info["body_json"],
        )
        _send_daleks_email(
            from_address=from_email,
            to=webhook_info["to"],
            subject=webhook_info["subject"],
            text_body=webhook_info["body"],
            html_body=html,
        )
        merchants_audit.info(
            "webhook_notification_sent: from=%r to=%r subject=%r",
            from_email,
            webhook_info["to"],
            webhook_info["subject"],
        )


def send_comprobante_abono(abono_info: dict):
    """Envía comprobante de abono al apoderado."""
    with current_app.app_context():
        from .database import db
        from .model import Payment

        pago = db.session.execute(db.select(Payment).filter_by(merchants_id=abono_info["codigo"])).scalar_one_or_none()
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
        _send_daleks_email(
            from_address=from_email,
            to=[abono_info["apoderado_email"]],
            subject=subject,
            text_body=body,
            html_body=html,
        )


def send_notificacion_admin_abono(abono_info: dict):
    """Notifica a los administradores sobre un abono aprobado."""
    with current_app.app_context():
        from .database import db
        from .model import Payment, Role

        pago = db.session.execute(db.select(Payment).filter_by(merchants_id=abono_info["codigo"])).scalar_one_or_none()

        admin_role = db.session.execute(db.select(Role).filter_by(name="admin")).scalar_one_or_none()
        if not admin_role:
            return
        admin_emails = [u.email for u in admin_role.users if u.email]
        if not admin_emails:
            return

        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono_info["codigo"], _external=True)
        subject = f"[admin] Abono aprobado - {abono_info['apoderado_nombre']} ${abono_info['monto']:,}"
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
                f"  Session ID: {pago.merchants_id}\n"
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
            saldo_anterior=abono_info.get("saldo_anterior"),
            saldo_cuenta=abono_info["saldo_cuenta"],
            pago_proveedor=pago.provider if pago else None,
            pago_estado=pago.state if pago else None,
            display_code=display_code,
            session_id=pago.merchants_id if pago else None,
            abono_url=abono_url,
        )
        from_email = _get_from_email()
        _send_daleks_email(
            from_address=from_email,
            to=admin_emails,
            subject=subject,
            text_body=body,
            html_body=html,
        )


def send_copia_notificaciones_abono(abono_info: dict):
    """Envía copia del comprobante de abono a los correos de copia_notificaciones."""
    copia_raw = abono_info.get("copia_notificaciones") or ""
    copia_emails = _parse_copia_emails(copia_raw)
    if not copia_emails:
        return
    with current_app.app_context():
        from .database import db
        from .model import Payment

        pago = db.session.execute(db.select(Payment).filter_by(merchants_id=abono_info["codigo"])).scalar_one_or_none()
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
        for email in copia_emails:
            _send_daleks_email(
                from_address=from_email,
                to=[email],
                subject=subject,
                text_body=body,
                html_body=html,
            )


def send_notificacion_abono_creado(abono_info: dict):
    """Notifica al apoderado que su abono fue recibido y le entrega el código de pago
    (sólo si comprobantes_transferencia es True). También envía copia a copia_notificaciones.
    Además notifica a todos los usuarios de los grupos admin y pos que alguien viene a pagar."""
    with current_app.app_context():
        from .database import db
        from .model import Abono as AbonoModel, Payment, Role

        pago = db.session.execute(db.select(Payment).filter_by(merchants_id=abono_info["codigo"])).scalar_one_or_none()
        abono_obj = db.session.execute(db.select(AbonoModel).filter_by(codigo=abono_info["codigo"])).scalar_one_or_none()
        display_code = _get_display_code(pago)
        abono_url = url_for("apoderado_cliente.abono_detalle", codigo=abono_info["codigo"], _external=True)
        try:
            from werkzeug.routing import BuildError
            admin_abono_url = url_for("abono.details_view", id=abono_obj.id, _external=True) if abono_obj else abono_url
        except BuildError:
            admin_abono_url = abono_url
        from_email = _get_from_email()

        # --- Email al apoderado y copias (sólo si comprobantes_transferencia es True) ---
        if abono_info.get("comprobantes_transferencia"):
            subject_apoderado = f"Solicitud de abono recibida - ${abono_info['monto']:,}"
            body_apoderado = (
                f"Hola {abono_info['apoderado_nombre']},\n\n"
                f"Tu solicitud de abono de ${abono_info['monto']:,} ha sido recibida.\n\n"
                f"Código: {abono_info['codigo'][:8].upper()}\n"
                f"Monto: ${abono_info['monto']:,}\n"
                f"Forma de pago: {abono_info['forma_pago']}\n"
            )
            if display_code:
                body_apoderado += f"\nPresenta este código en la cafetería del colegio: {display_code}\n"
            else:
                body_apoderado += f"\nDirígete a la cafetería del colegio para realizar el pago.\n"
            body_apoderado += f"\nVer detalle: {abono_url}\n\nSaludos,\nCafetería SaborMirandiano"
            html_apoderado = render_template(
                "core/emails/nuevo_abono_pendiente_apoderado.html",
                nombre_apoderado=abono_info["apoderado_nombre"],
                monto=abono_info["monto"],
                forma_pago=abono_info["forma_pago"],
                codigo=abono_info["codigo"][:8].upper(),
                display_code=display_code,
                abono_url=abono_url,
            )
            recipients = [abono_info["apoderado_email"]]
            copia_emails = _parse_copia_emails(abono_info.get("copia_notificaciones") or "")
            recipients.extend(copia_emails)
            for recipient in recipients:
                _send_daleks_email(
                    from_address=from_email,
                    to=[recipient],
                    subject=subject_apoderado,
                    text_body=body_apoderado,
                    html_body=html_apoderado,
                )

        # --- Email a los administradores y usuarios pos (aviso de pago presencial, sin QR) ---
        admin_role = db.session.execute(db.select(Role).filter_by(name="admin")).scalar_one_or_none()
        pos_role = db.session.execute(db.select(Role).filter_by(name="pos")).scalar_one_or_none()
        staff_emails = list({
            u.email
            for role in (admin_role, pos_role)
            if role
            for u in role.users
            if u.email
        })
        if staff_emails:
            subject_admin = f"[aviso] Nuevo abono pendiente - {abono_info['apoderado_nombre']} ${abono_info['monto']:,}"
            body_admin = (
                f"Se ha generado un código de abono en la cafetería. Este pago aún NO ha sido procesado.\n\n"
                f"Apoderado: {abono_info['apoderado_nombre']} ({abono_info['apoderado_email']})\n"
                f"Código abono: {abono_info['codigo']}\n"
                f"Monto: ${abono_info['monto']:,}\n"
                f"Forma de pago: {abono_info['forma_pago']}\n"
            )
            if display_code:
                body_admin += f"Código de pago: {display_code}\n"
            body_admin += f"\nVer y aprobar: {admin_abono_url}"
            html_admin = render_template(
                "core/emails/nuevo_abono_pendiente_admin.html",
                nombre_apoderado=abono_info["apoderado_nombre"],
                email_apoderado=abono_info["apoderado_email"],
                monto=abono_info["monto"],
                forma_pago=abono_info["forma_pago"],
                codigo=abono_info["codigo"],
                descripcion=abono_info.get("descripcion"),
                pago_proveedor=pago.provider if pago else None,
                display_code=display_code,
                session_id=pago.merchants_id if pago else None,
                abono_url=abono_url,
                admin_abono_url=admin_abono_url,
            )
            _send_daleks_email(
                from_address=from_email,
                to=staff_emails,
                subject=subject_admin,
                text_body=body_admin,
                html_body=html_admin,
            )


def send_notificacion_pedido_pendiente(pedido_info: dict):
    """Notifica al apoderado que su pedido fue recibido y está pendiente de pago.

    Si la forma de pago es cafetería se incluyen instrucciones y el código QR.
    Si el proveedor genera una URL de redirección (p. ej. Khipu) se incluye un
    botón para completar el pago.  Siempre envía copia [ADMIN] a todos los
    usuarios con rol admin.  Si el apoderado tiene copia_notificaciones
    configurado, también envía a esas direcciones (cuando notificacion_compra=True).
    """
    with current_app.app_context():
        from .database import db
        from .model import Alumno, Apoderado, Payment, Role

        # Resolve apoderados from alumno IDs stored in the pedido items
        alumno_ids = [
            int(a["id"])
            for item in pedido_info.get("items", [])
            for a in item.get("alumnos", [])
        ]
        apoderados: dict[int, Apoderado] = {}
        if alumno_ids:
            alumnos = (
                db.session.execute(db.select(Alumno).filter(Alumno.id.in_(alumno_ids)))
                .scalars()
                .all()
            )
            for alumno in alumnos:
                ap = alumno.apoderado
                if ap and ap.id not in apoderados:
                    apoderados[ap.id] = ap

        if not apoderados:
            return

        # Resolve payment for display_code
        pago = db.session.execute(
            db.select(Payment).filter_by(merchants_id=pedido_info.get("merchants_id", ""))
        ).scalar_one_or_none()
        display_code = _get_display_code(pago)
        redirect_url = pedido_info.get("redirect_url", "")
        forma_pago = pedido_info.get("forma_pago", "")
        total = pedido_info.get("total", 0)
        pedido_codigo = pedido_info.get("pedido_codigo", "")
        pedido_codigo_short = pedido_codigo[:8].upper()
        pedido_url = pedido_info.get("pedido_url", "")

        from_email = _get_from_email()
        admin_role = db.session.execute(
            db.select(Role).filter_by(name="admin")
        ).scalar_one_or_none()
        admin_emails = [u.email for u in admin_role.users if u.email] if admin_role else []

        last_subject = None
        last_body = None
        last_html = None

        for apoderado in apoderados.values():
            email = apoderado.usuario.email if apoderado.usuario else None

            subject = f"Pedido recibido #{pedido_codigo_short} - ${int(total):,}"
            body = (
                f"Hola {apoderado.nombre},\n\n"
                f"Hemos recibido tu pedido de menús por un total de ${int(total):,}.\n\n"
                f"N° de pedido: {pedido_codigo_short}\n"
                f"Forma de pago: {forma_pago}\n"
            )
            if forma_pago == "cafeteria" and display_code:
                body += (
                    f"\nDirígete a la cafetería del colegio y presenta el código: {display_code}\n"
                )
            elif redirect_url:
                body += f"\nCompleta tu pago en: {redirect_url}\n"
            body += f"\nVer detalle: {pedido_url}\n\nSaludos,\nCafetería Sabor Mirandiano"

            html = render_template(
                "core/emails/order-nueva-compra/compiled.html",
                nombre_apoderado=apoderado.nombre,
                pedido_codigo=pedido_codigo_short,
                items=pedido_info.get("items", []),
                total=total,
                forma_pago=forma_pago,
                display_code=display_code,
                redirect_url=redirect_url,
                pedido_url=pedido_url,
            )

            last_subject = subject
            last_body = body
            last_html = html

            if apoderado.notificacion_compra and email:
                _send_daleks_email(
                    from_address=from_email,
                    to=[email],
                    subject=subject,
                    text_body=body,
                    html_body=html,
                )
                copia_emails = _parse_copia_emails(apoderado.copia_notificaciones or "")
                for copia_email in copia_emails:
                    _send_daleks_email(
                        from_address=from_email,
                        to=[copia_email],
                        subject=subject,
                        text_body=body,
                        html_body=html,
                    )

        if admin_emails and last_subject:
            admin_subject = f"[ADMIN] {last_subject}"
            _send_daleks_email(
                from_address=from_email,
                to=admin_emails,
                subject=admin_subject,
                text_body=last_body,
                html_body=last_html,
            )



_MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def send_confirmacion_orden_pagado(pedido_info: dict):
    """Notifica al apoderado la confirmación de sus almuerzos tras pagar el pedido.

    Sends to the Apoderado when notificacion_compra=True, to
    copia_notificaciones when set, and always sends an [ADMIN] copy to all
    users with the admin role.
    """
    with current_app.app_context():
        from datetime import date as _date

        from .database import db
        from .model import Apoderado, Role

        apoderado_id = pedido_info.get("apoderado_id")
        if not apoderado_id:
            return

        apoderado = db.session.get(Apoderado, int(apoderado_id))
        if not apoderado:
            return

        pedido_codigo = pedido_info.get("pedido_codigo", "")
        pedido_codigo_short = pedido_codigo[:8].upper() if pedido_codigo else ""
        total = pedido_info.get("total", 0)
        items = list(pedido_info.get("items", []))
        pedido_url = url_for("apoderado_cliente.pago_orden", orden=pedido_codigo, _external=True)

        # Enrich items with Spanish date components for the calendar template
        for item in items:
            try:
                d = _date.fromisoformat(item.get("fecha", ""))
                item["dia"] = f"{d.day:02d}"
                item["mes_abr"] = _MESES_ES[d.month - 1]
            except (ValueError, IndexError):
                item["dia"] = ""
                item["mes_abr"] = ""

        subject = f"Confirmación de almuerzos #{pedido_codigo_short}"
        body = (
            f"Hola {apoderado.nombre},\n\n"
            f"Tus almuerzos han sido confirmados.\n\n"
            f"N° de pedido: {pedido_codigo_short}\n"
            f"Total: ${int(total):,}\n\n"
        )
        for item in items:
            body += f"- {item['fecha']}: {item['descripcion']} ({item['alumnos_str']})\n"
        body += f"\nVer detalle: {pedido_url}\n\nSaludos,\nCafetería Sabor Mirandiano"

        html = render_template(
            "core/emails/confirmacion_orden.html",
            nombre_apoderado=apoderado.nombre,
            pedido_codigo=pedido_codigo_short,
            items=items,
            total=total,
            pedido_url=pedido_url,
        )
        from_email = _get_from_email()

        if apoderado.notificacion_compra:
            email = apoderado.usuario.email if apoderado.usuario else None
            if email:
                _send_daleks_email(
                    from_address=from_email,
                    to=[email],
                    subject=subject,
                    text_body=body,
                    html_body=html,
                )
            copia_emails = _parse_copia_emails(apoderado.copia_notificaciones or "")
            for copia_email in copia_emails:
                _send_daleks_email(
                    from_address=from_email,
                    to=[copia_email],
                    subject=subject,
                    text_body=body,
                    html_body=html,
                )

        admin_role = db.session.execute(
            db.select(Role).filter_by(name="admin")
        ).scalar_one_or_none()
        admin_emails = [u.email for u in admin_role.users if u.email] if admin_role else []
        if admin_emails:
            admin_subject = f"[ADMIN] {subject}"
            _send_daleks_email(
                from_address=from_email,
                to=admin_emails,
                subject=admin_subject,
                text_body=body,
                html_body=html,
            )


def send_notificacion_admin_nuevo_apoderado(apoderado_info: dict):
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

        subject = f"[admin] Nuevo apoderado registrado - {apoderado_info['nombre_apoderado']}"
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
        _send_daleks_email(
            from_address=from_email,
            to=admin_emails,
            subject=subject,
            text_body=body,
            html_body=html,
        )


def send_confirmacion_staff_pedido_pagado(pedido_info: dict):
    """Notifica al personal del colegio la confirmación de su pedido pagado."""
    with current_app.app_context():
        from .database import db
        from .model import SchoolStaff

        staff_id = pedido_info.get("staff_id")
        if not staff_id:
            return

        staff = db.session.get(SchoolStaff, int(staff_id))
        if not staff:
            return

        email = staff.usuario.email if staff.usuario else None
        if not email:
            return

        pedido_codigo = pedido_info.get("pedido_codigo", "")
        pedido_codigo_short = pedido_codigo[:8].upper() if pedido_codigo else ""
        total = pedido_info.get("total", 0)

        subject = f"Confirmación de pedido #{pedido_codigo_short}"
        body = (
            f"Hola {staff.nombre},\n\n"
            f"Tu pedido ha sido confirmado.\n\n"
            f"N° de pedido: {pedido_codigo_short}\n"
            f"Total: ${int(total):,}\n\n"
            f"Saludos,\nCafetería SaborMirandiano"
        )
        html = render_template(
            "staff/emails/confirmacion_pedido.html",
            nombre_staff=staff.nombre,
            pedido_codigo=pedido_codigo_short,
            total=total,
        )
        from_email = _get_from_email()
        _send_daleks_email(
            from_address=from_email,
            to=[email],
            subject=subject,
            text_body=body,
            html_body=html,
        )


def send_informe_mensual_staff():
    """Envía a cada miembro del personal su deuda del mes al final de cada mes.

    Disparado automáticamente por el scheduler de solicitudes (``app/staff/scheduler.py``).
    Incluye instrucciones para pagar en un plazo de 5 días hábiles.
    """
    with current_app.app_context():
        from .database import db
        from .model import SchoolStaff, SchoolStaffPedido, EstadoPedido
        from sqlalchemy import and_, func
        from decimal import Decimal
        import datetime as _dt

        today = _dt.date.today()
        inicio_mes = today.replace(day=1)

        all_staff = db.session.execute(db.select(SchoolStaff)).scalars().all()
        from_email = _get_from_email()

        for staff in all_staff:
            email = staff.usuario.email if staff.usuario else None
            if not email:
                continue

            deuda = db.session.execute(
                db.select(func.coalesce(func.sum(SchoolStaffPedido.precio_total), 0)).where(
                    and_(
                        SchoolStaffPedido.staff_id == staff.id,
                        SchoolStaffPedido.pagado == False,  # noqa: E712
                        SchoolStaffPedido.estado != EstadoPedido.CANCELADA,
                        SchoolStaffPedido.fecha_pedido >= inicio_mes,
                    )
                )
            ).scalar() or Decimal(0)

            if deuda <= 0:
                continue

            subject = f"Estado de cuenta mensual - ${int(deuda):,} a pagar"
            body = (
                f"Hola {staff.nombre},\n\n"
                f"El saldo pendiente de tu cuenta del casino correspondiente al mes de "
                f"{today.strftime('%B %Y')} es de ${int(deuda):,}.\n\n"
                f"Tienes 5 días hábiles a partir de hoy para realizar el pago.\n\n"
                f"Puedes pagar en la cafetería del colegio o a través de la plataforma.\n\n"
                f"Saludos,\nCafetería SaborMirandiano"
            )
            html = render_template(
                "staff/emails/informe_mensual.html",
                nombre_staff=staff.nombre,
                deuda=int(deuda),
                mes=today.strftime("%B %Y"),
            )
            _send_daleks_email(
                from_address=from_email,
                to=[email],
                subject=subject,
                text_body=body,
                html_body=html,
            )


def send_informe_semanal_staff():
    """Envía el resumen semanal de deuda a los miembros del personal que lo soliciten.

    Disparado automáticamente por el scheduler de solicitudes (``app/staff/scheduler.py``).
    Solo se envía a quienes tienen ``informe_semanal=True``.
    """
    with current_app.app_context():
        from .database import db
        from .model import SchoolStaff, SchoolStaffPedido, EstadoPedido
        from sqlalchemy import and_, func
        from decimal import Decimal

        all_staff = db.session.execute(
            db.select(SchoolStaff).filter_by(informe_semanal=True)
        ).scalars().all()
        from_email = _get_from_email()

        for staff in all_staff:
            email = staff.usuario.email if staff.usuario else None
            if not email:
                continue

            deuda = db.session.execute(
                db.select(func.coalesce(func.sum(SchoolStaffPedido.precio_total), 0)).where(
                    and_(
                        SchoolStaffPedido.staff_id == staff.id,
                        SchoolStaffPedido.pagado == False,  # noqa: E712
                        SchoolStaffPedido.estado != EstadoPedido.CANCELADA,
                    )
                )
            ).scalar() or Decimal(0)

            subject = f"Resumen semanal de cuenta - saldo pendiente ${int(deuda):,}"
            body = (
                f"Hola {staff.nombre},\n\n"
                f"Tu saldo pendiente en la cafetería del colegio es de ${int(deuda):,}.\n\n"
                f"Recuerda que la deuda se cobra al final de cada mes.\n\n"
                f"Saludos,\nCafetería SaborMirandiano"
            )
            html = render_template(
                "staff/emails/informe_semanal.html",
                nombre_staff=staff.nombre,
                deuda=int(deuda),
            )
            _send_daleks_email(
                from_address=from_email,
                to=[email],
                subject=subject,
                text_body=body,
                html_body=html,
            )
