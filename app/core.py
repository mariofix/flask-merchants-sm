import os

import merchants as _merchants
import redis as _redis
from dotenv import load_dotenv
from flask import Flask, url_for
from flask_admin import helpers as admin_helpers
from flask_security.core import Security
from flask_security.datastore import SQLAlchemyUserDatastore
from werkzeug.middleware.proxy_fix import ProxyFix

from .apoderado.route import apoderado_bp
from .flyers.route import flyers_bp
from .celery import celery_init_app
from .docs import docs_bp
from .database import db, migrations
from .extensions import babel, csrf, flask_merchants, mail, limiter
from .extensions.admin import admin, SecureRedisCli
from .logging_config import configure_logging
from .model import *  # noqa: F403
from .pos.routes import pos_bp
from .providers.cafeteria import CafeteriaProvider
from .providers.saldo import SaldoProvider
from .routes import core_bp
from .staff.route import staff_bp
from .tasks import MyMailUtil
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

    # Redis CLI console(s); a second view is only added when broker and result backend differ
    celery_cfg = app.config.get("CELERY", {})
    broker_url = celery_cfg.get("broker_url", "")
    result_backend = celery_cfg.get("result_backend", "")
    if broker_url and broker_url.startswith("redis"):
        admin.add_view(
            SecureRedisCli(
                _redis.from_url(broker_url, socket_connect_timeout=2),
                name="Redis Cola",
                endpoint="redis_broker",
                category="Herramientas",
            )
        )
    if result_backend and result_backend.startswith("redis") and result_backend != broker_url:
        admin.add_view(
            SecureRedisCli(
                _redis.from_url(result_backend, socket_connect_timeout=2),
                name="Redis Resultados",
                endpoint="redis_results",
                category="Herramientas",
            )
        )

    # Setup Flask-Security
    from .forms import ChileanPhoneUsernameUtil

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security = Security(
        app,
        user_datastore,
        mail_util_cls=MyMailUtil,
        username_util_cls=ChileanPhoneUsernameUtil,
    )
    app.extensions["user_datastore"] = user_datastore
    # Flask-Mailman
    mail.init_app(app)

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
        providers.append(KhipuProvider(api_key=khipu_api_key))
    providers.append(CafeteriaProvider())
    providers.append(SaldoProvider())

    # merchants - do not pass admin here; we register a custom PaymentAdminView
    # separately after webhook configuration (see below)
    flask_merchants.init_app(app=app, db=db, models=[Payment], providers=providers)

    # Register Khipu abono approval webhook handler.
    # When Khipu notifies /merchants/webhook/khipu that a payment succeeded,
    # this handler finds the matching Payment record via khipu_payment_id stored
    # in metadata_json, sets the state to "succeeded", and credits the
    # apoderado's saldo_cuenta with the abono amount.
    def _khipu_abono_webhook_handler(event) -> None:
        import logging as _logging
        _wh_logger = _logging.getLogger(__name__)
        _wh_logger.debug(
            "core.py: _khipu_abono_webhook_handler called with provider=%r state=%r payment_id=%r",
            event.provider, event.state, event.payment_id,
        )
        from merchants.models import PaymentState
        from flask_merchants import merchants_audit
        from .model import Abono

        if event.provider != "khipu" or event.state != PaymentState.SUCCEEDED:
            return
        if not event.payment_id:
            return

        # Load pending khipu payments and match in Python for database portability
        # (JSON path queries differ between SQLite used in tests and PostgreSQL in prod).
        pending_pagos = (
            db.session.execute(
                db.select(Payment).where(
                    Payment.provider == "khipu",
                    Payment.state == "pending",
                )
            )
            .scalars()
            .all()
        )
        pago = next(
            (
                p
                for p in pending_pagos
                if (p.metadata_json or {}).get("khipu_payment_id") == event.payment_id
            ),
            None,
        )

        # Re-check pago.state as an idempotency guard: a concurrent duplicate webhook
        # could have already committed a state change after our SELECT above.
        if pago and pago.state == "pending":
            abono = db.session.execute(
                db.select(Abono).filter_by(codigo=pago.session_id)
            ).scalar_one_or_none()
            if abono:
                pago.state = "succeeded"
                saldo_actual = abono.apoderado.saldo_cuenta or 0
                abono.apoderado.saldo_cuenta = saldo_actual + int(abono.monto)
                db.session.commit()
                merchants_audit.info(
                    "abono_aprobado_khipu_webhook: codigo=%s apoderado_id=%s monto=%s nuevo_saldo=%s",
                    abono.codigo,
                    abono.apoderado.id,
                    int(abono.monto),
                    abono.apoderado.saldo_cuenta,
                )

    flask_merchants.add_webhook_handler(_khipu_abono_webhook_handler)

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
    _labels = app.config.get("MERCHANTS_PROVIDER_LABELS", {})
    _providers_ctx = []
    for p in _merchants.describe_providers():
        label = _labels.get(p.key, {})
        _providers_ctx.append({
            "key": p.key,
            "title": label.get("title", p.name),
            "subtitle": label.get("subtitle", p.description),
        })

    @app.context_processor
    def default_data():
        return {
            "app_version": __version__,
            "payment_providers": _providers_ctx,
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

    # Celery
    celery_init_app(app)

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
