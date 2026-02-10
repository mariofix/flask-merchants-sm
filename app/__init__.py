from .core import create_app

# from typing import Optional

# from flask import Flask, render_template, request, session  # , url_for
# from flask_babel import Babel
# from flask_debugtoolbar import DebugToolbarExtension
# from werkzeug.middleware.proxy_fix import ProxyFix

# from flask_merchants.core import FlaskMerchantsExtension

# from .database import db, migrations
# from .model import *  # noqa: F403
# # from ...store_orig.modules.storefront.route import storefront_bp
# from .views import ProductView

# merchants = FlaskMerchantsExtension()


# def create_app(settings_file: str | None = None):
#     app = Flask("Store", template_folder="store/templates", static_folder="store/static")
#     app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

#     # Configure App, env takes precedence
#     if settings_file:
#         app.config.from_object(settings_file)
#     app.config.from_prefixed_env()

#     # SQLAlchemy&Flask-Migrate
#     db.init_app(app)
#     migrations.init_app(app, db, directory="store/migrations")

#     # Flask-Merchants
#     merchants.init_app(app, db)
#     merchants.add_admin_model(Product, ProductView)  # noqa: F405

#     # Flask-DebugToolbar
#     if app.debug:
#         # toolbar = DebugToolbarExtension()
#         # toolbar.init_app(app)
#         pass

#     # Flask-babel
#     babel = Babel()

#     def get_locale():
#         if request.args.get("lang"):
#             session["lang"] = request.args.get("lang")
#         return session.get("lang", app.config.get("BABEL_DEFAULT_LOCALE"))

#     def get_timezone():
#         return app.config.get("BABEL_DEFAULT_TIMEZONE")

#     babel.init_app(
#         app,
#         locale_selector=get_locale,
#         timezone_selector=get_timezone,
#         default_domain=app.config.get("BABEL_DOMAIN", "merchants"),
#         default_translation_directories=app.config.get("BABEL_DEFAULT_FOLDER", "store/translations"),
#     )

#     @app.context_processor
#     def default_data() -> dict:
#         return {
#             "app_version": "2025.3.1",
#         }

#     # app.register_blueprint(storefront_bp)

#     @app.get("/_storefront/")
#     def _storefront():
#         return render_template("store/storefront-2.html")

#     return app
