import os

import merchants as _merchants
from daleks.contrib.flask_security_mail import DaleksMailUtil
from dotenv import load_dotenv
from flask import Flask, url_for
from flask_admin import helpers as admin_helpers
from flask_security.core import Security
from flask_security.datastore import SQLAlchemyUserDatastore
from werkzeug.middleware.proxy_fix import ProxyFix

from .apoderado.route import apoderado_bp
from .flyers.route import flyers_bp
from .docs import docs_bp
from .database import db, migrations
from .extensions import babel, csrf, flask_merchants, limiter
from .extensions.admin import admin
from .logging_config import configure_logging
from .model import *  # noqa: F403
from .pos.routes import pos_bp
from .providers.cafeteria import CafeteriaProvider
from .providers.saldo import SaldoProvider
from .routes import core_bp
from .staff.route import staff_bp
from .version import __version__


load_dotenv()


def create_app():
    app = Flask(
        "merchants-sabormirandiano",
        template_folder="app/templates",
        static_folder="app/static",
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Configure App, env takes precedence
    settings_file = os.getenv("FLASK_APP_SETTINGS_FILE", None)
    if settings_file:
        app.config.from_object(settings_file)
    app.config.from_prefixed_env()

    # Logging — set up sm.app / sm.celery / sm.audit before anything else logs
    configure_logging(app)

    # Extensions
    babel.init_app(app)
    db.init_app(app)
    migrations.init_app(app, db, directory="app/migrations")
    admin.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Setup Flask-Security
    from .forms import ChileanPhoneUsernameUtil

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security = Security(
        app,
        user_datastore,
        mail_util_cls=DaleksMailUtil,
        username_util_cls=ChileanPhoneUsernameUtil,
    )
    app.extensions["user_datastore"] = user_datastore

    # Wire Flask-Login / Flask-Security signals to sm.app and sm.audit loggers
    _register_auth_signals(app)

    @security.context_processor
    def security_context_processor():
        return dict(
            admin_base_template=admin.theme.base_template,
            admin_view=admin.index_view,
            theme=admin.theme,
            h=admin_helpers,
            get_url=url_for,
        )

    # Build payment providers from config/env
    providers = []
    khipu_api_key = app.config.get("KHIPU_API_KEY", "")
    if khipu_api_key:
        # Only register Khipu when a real API key is configured.
        from merchants.providers.khipu import KhipuProvider
        khipu_subject = app.config.get("KHIPU_SUBJECT", "Pago SaborMirandiano")
        khipu_webhook_secret = app.config.get("KHIPU_WEBHOOK_SECRET", "")
        providers.append(KhipuProvider(
            api_key=khipu_api_key,
            subject=khipu_subject,
            webhook_secret=khipu_webhook_secret,
        ))
    providers.append(CafeteriaProvider())
    providers.append(SaldoProvider())

    # merchants - do not pass admin here; we register a custom PaymentAdminView
    # separately after webhook configuration (see below)
    flask_merchants.init_app(app=app, db=db, models=[Payment], providers=providers)

    # Register Khipu webhook handler.
    # When Khipu notifies /merchants/webhook/khipu that a payment succeeded,
    # this handler finds the matching Payment record via transaction_id,
    # and processes the associated entity:
    #   - Abono: credits apoderado.saldo_cuenta, sends receipt emails.
    #   - Pedido: marks as paid, creates OrdenCasino rows, sends confirmation emails.
    #
    # Note: by the time this handler fires, views.py has already called
    # ext.update_state() which sets pago.state = "succeeded" and commits.
    # We use payment_object being empty as our idempotency guard: the handler
    # populates it once, and skips on duplicate webhooks.
    def _khipu_webhook_handler(event) -> None:
        import logging as _logging
        _wh_logger = _logging.getLogger(__name__)
        _wh_logger.debug(
            "core.py: _khipu_webhook_handler called with provider=%r state=%r payment_id=%r",
            event.provider, event.state, event.payment_id,
        )
        from merchants.models import PaymentState
        from flask_merchants import merchants_audit
        from .model import Abono, Pedido, EstadoPedido

        if event.provider != "khipu" or event.state != PaymentState.SUCCEEDED:
            return
        if not event.payment_id:
            return

        # v3.0 webhook body contains both payment_id (Khipu's ID, stored as
        # Payment.transaction_id) and transaction_id (merchant's order ID,
        # stored as Payment.merchants_id).  Look up by Khipu's payment_id
        # → our Payment.transaction_id.
        pago = db.session.execute(
            db.select(Payment).where(
                Payment.provider == "khipu",
                Payment.transaction_id == event.payment_id,
            )
        ).scalar_one_or_none()

        if not pago:
            return

        # Idempotency: if payment_object is already populated, this webhook
        # has already been processed (duplicate delivery from Khipu).
        if pago.payment_object:
            _wh_logger.info(
                "core.py: duplicate webhook skipped for payment_id=%r (already processed)",
                event.payment_id,
            )
            return

        # Store the full webhook payload for audit/reconciliation
        pago.payment_object = event.raw

        # Determine whether this payment belongs to an abono or a pedido
        abono = db.session.execute(
            db.select(Abono).filter_by(codigo=pago.merchants_id)
        ).scalar_one_or_none()

        if abono:
            _handle_abono_payment(pago, abono, event, merchants_audit)
            return

        pedido = db.session.execute(
            db.select(Pedido).filter_by(codigo_merchants=pago.merchants_id)
        ).scalar_one_or_none()

        if pedido:
            _handle_pedido_payment(pago, pedido, event, merchants_audit)
            return

        # No linked entity found — still commit payment_object so the
        # webhook data is preserved and this won't be re-processed.
        db.session.commit()
        _wh_logger.warning(
            "core.py: no abono or pedido found for payment merchants_id=%r (khipu payment_id=%r)",
            pago.merchants_id, event.payment_id,
        )

    def _handle_abono_payment(pago, abono, event, merchants_audit) -> None:
        """Process a successful Khipu payment for an abono (deposit).

        State is already "succeeded" (set by ext.update_state in the webhook view).
        """
        saldo_actual = abono.apoderado.saldo_cuenta or 0
        abono.apoderado.saldo_cuenta = saldo_actual + int(abono.monto)
        db.session.commit()
        merchants_audit.info(
            "abono_aprobado_khipu_webhook: codigo=%s apoderado_id=%s monto=%s nuevo_saldo=%s khipu_payment_id=%s",
            abono.codigo,
            abono.apoderado.id,
            int(abono.monto),
            abono.apoderado.saldo_cuenta,
            event.payment_id,
        )

        # Send receipt and admin notification emails (same pattern as POS approval)
        from .tasks import (
            send_comprobante_abono,
            send_notificacion_admin_abono,
            send_copia_notificaciones_abono,
        )

        abono_info = {
            "id": abono.id,
            "codigo": abono.codigo,
            "monto": int(abono.monto),
            "forma_pago": abono.forma_pago,
            "descripcion": abono.descripcion,
            "apoderado_nombre": abono.apoderado.nombre,
            "apoderado_email": abono.apoderado.usuario.email,
            "saldo_cuenta": abono.apoderado.saldo_cuenta,
            "copia_notificaciones": abono.apoderado.copia_notificaciones,
        }
        send_notificacion_admin_abono(abono_info=abono_info)
        if abono.apoderado.comprobantes_transferencia:
            send_comprobante_abono(abono_info=abono_info)
            if abono.apoderado.copia_notificaciones:
                send_copia_notificaciones_abono(abono_info=abono_info)

    def _handle_pedido_payment(pago, pedido, event, merchants_audit) -> None:
        """Process a successful Khipu payment for a pedido (order).

        Payment state is already "succeeded" (set by ext.update_state in the webhook view).
        """
        from datetime import datetime as _dt
        from .model import EstadoPedido
        from .apoderado.controller import ApoderadoController

        pedido.estado = EstadoPedido.PAGADO
        pedido.pagado = True
        pedido.fecha_pago = _dt.now()
        db.session.commit()

        merchants_audit.info(
            "pedido_pagado_khipu_webhook: codigo=%s apoderado_id=%s total=%s khipu_payment_id=%s",
            pedido.codigo,
            pedido.apoderado_id,
            int(pedido.precio_total),
            event.payment_id,
        )

        # Create OrdenCasino rows and send confirmation emails
        ctrl = ApoderadoController()
        ctrl.process_payment_completion(pedido)

    flask_merchants.add_webhook_handler(_khipu_webhook_handler)

    # Enable webhook notification emails to admin users.
    # Every incoming webhook triggers an email containing provider, transaction,
    # headers and body so administrators can inspect provider payloads.
    from .tasks import send_webhook_notification_email

    def _get_admin_emails() -> list[str]:
        admin_role = db.session.execute(
            db.select(Role).filter_by(name="admin")
        ).scalar_one_or_none()
        if not admin_role:
            return []
        return [u.email for u in admin_role.users if u.email]

    flask_merchants.enable_webhook_notifications(
        admin_emails_fn=_get_admin_emails,
        send_fn=lambda info: send_webhook_notification_email(info),
    )

    # Register custom payment admin views (using PaymentAdminView with app-specific actions).
    # Replaces the default PaymentModelView that would have been auto-registered via admin=admin.
    from .extensions.admin import PaymentAdminView
    from flask_merchants.contrib.admin import ProvidersView

    payment_view_name = app.config.get("MERCHANTS_PAYMENT_VIEW_NAME", "Payments")
    provider_view_name = app.config.get("MERCHANTS_PROVIDER_VIEW_NAME", "Providers")
    admin.add_view(
        PaymentAdminView(
            Payment,
            db.session,
            ext=flask_merchants,
            name=payment_view_name,
            endpoint="merchants_merchants_payment",
            category="Merchants",
        )
    )
    admin.add_view(
        ProvidersView(
            flask_merchants,
            name=provider_view_name,
            endpoint="merchants_providers",
            category="Merchants",
        )
    )

    # Build the providers context once (providers don't change after init).
    # `payment_providers` includes all providers (for pedido payment forms).
    # `abono_payment_providers` excludes internal-only providers (saldo) that
    # are not valid for abonos (deposit top-ups).
    _labels = app.config.get("MERCHANTS_PROVIDER_LABELS", {})
    _providers_ctx = []
    for p in _merchants.describe_providers():
        label = _labels.get(p.key, {})
        _providers_ctx.append({
            "key": p.key,
            "title": label.get("title", p.name),
            "subtitle": label.get("subtitle", p.description),
        })
    _abono_providers_ctx = [p for p in _providers_ctx if p["key"] != "saldo"]

    @app.context_processor
    def default_data():
        return {
            "app_version": __version__,
            "payment_providers": _providers_ctx,
            "abono_payment_providers": _abono_providers_ctx,
        }

    app.register_blueprint(core_bp)
    app.register_blueprint(apoderado_bp, url_prefix="/apoderado")
    app.register_blueprint(pos_bp, url_prefix="/pos")
    app.register_blueprint(staff_bp, url_prefix="/staff")
    app.register_blueprint(docs_bp)
    app.register_blueprint(flyers_bp)

    # Request-based scheduler for school staff periodic emails
    from .staff.scheduler import check_and_fire_staff_jobs
    app.before_request(check_and_fire_staff_jobs)

    # REMOVE BEFORE PRODUCTION
    if app.debug:
        from flask_debugtoolbar import DebugToolbarExtension

        toolbar = DebugToolbarExtension()
        toolbar.init_app(app)

    return app


# ---------------------------------------------------------------------------
# Auth signal handlers
# ---------------------------------------------------------------------------

def _register_auth_signals(app) -> None:  # noqa: ANN001
    """Connect Flask-Login / Flask-Security signals to the app and audit loggers."""
    import logging
    from flask_login.signals import user_logged_in, user_logged_out
    from flask_security.signals import (
        user_registered,
        password_changed,
        password_reset,
    )

    app_log = logging.getLogger("sm.app")
    audit_log = logging.getLogger("sm.audit")

    @user_logged_in.connect_via(app)
    def on_login(sender: object, user: object, **kwargs: object) -> None:
        app_log.info(
            "login: user_id=%s username=%r email=%r",
            getattr(user, "id", None),
            getattr(user, "username", None),
            getattr(user, "email", None),
        )

    @user_logged_out.connect_via(app)
    def on_logout(sender: object, user: object, **kwargs: object) -> None:
        app_log.info(
            "logout: user_id=%s username=%r",
            getattr(user, "id", None),
            getattr(user, "username", None),
        )

    @user_registered.connect_via(app)
    def on_registered(sender: object, user: object, **kwargs: object) -> None:
        audit_log.info(
            "nuevo_usuario_registrado: user_id=%s username=%r email=%r",
            getattr(user, "id", None),
            getattr(user, "username", None),
            getattr(user, "email", None),
        )

    @password_changed.connect_via(app)
    def on_password_changed(sender: object, user: object, **kwargs: object) -> None:
        app_log.info(
            "password_changed: user_id=%s username=%r",
            getattr(user, "id", None),
            getattr(user, "username", None),
        )

    @password_reset.connect_via(app)
    def on_password_reset(sender: object, user: object, **kwargs: object) -> None:
        app_log.info(
            "password_reset: user_id=%s username=%r",
            getattr(user, "id", None),
            getattr(user, "username", None),
        )
