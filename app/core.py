import os

import merchants as _merchants
from dotenv import load_dotenv
from flask import Flask, url_for
from flask_admin import helpers as admin_helpers
from flask_security.core import Security
from flask_security.datastore import SQLAlchemyUserDatastore
from werkzeug.middleware.proxy_fix import ProxyFix

from .apoderado.route import apoderado_bp
from .celery import celery_init_app
from .database import db, migrations
from .extensions import babel, csrf, flask_merchants, mail
from .extensions.admin import admin
from .model import *  # noqa: F403
from .pos.routes import pos_bp
from .providers.cafeteria import CafeteriaProvider
from .routes import core_bp
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

    # Extensions
    babel.init_app(app)
    db.init_app(app)
    migrations.init_app(app, db, directory="app/migrations")
    admin.init_app(app)
    csrf.init_app(app)

    # Setup Flask-Security
    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security = Security(app, user_datastore, mail_util_cls=MyMailUtil)
    app.extensions["user_datastore"] = user_datastore
    # Flask-Mailman
    mail.init_app(app)

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

    # merchants
    flask_merchants.init_app(app=app, db=db, models=[Payment], admin=admin, providers=providers)

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

    # Celery
    celery_init_app(app)

    # REMOVE BEFORE PRODUCTION
    if app.debug:
        from flask_debugtoolbar import DebugToolbarExtension

        toolbar = DebugToolbarExtension()
        toolbar.init_app(app)

    return app
