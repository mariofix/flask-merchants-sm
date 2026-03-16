import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY: str
DEBUG = True
LOG_LEVEL = "DEBUG" if DEBUG else "INFO"
TRUSTED_HOSTS = ["tardis.local", "192.168.110.133"]
SERVER_NAME = TRUSTED_HOSTS[0]
SESSION_COOKIE_NAME = "sabormirandiano"
DIRECTORIO_FOTOS_PLATO = f"{BASE_DIR}/app/static/platos"

SQLALCHEMY_DATABASE_URI = ""
SQLALCHEMY_RECORD_QUERIES = DEBUG
SQLALCHEMY_ECHO = False
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 1800}

SECURITY_EMAIL_SUBJECT_REGISTER = "Bienvenida a Sabor Mirandiano"
SECURITY_EMAIL_SENDER = "Sabor Mirandiano"
SECURITY_PASSWORD_SALT = "password-salt-randomnesssss.0"
SECURITY_POST_LOGIN_VIEW = "/dispatcher"
SECURITY_POST_LOGOUT_VIEW = "/"
SECURITY_POST_REGISTER_VIEW = "/confirm"
SECURITY_POST_CONFIRM_VIEW = "/apoderado/wizard"
SECURITY_UNAUTHORIZED_VIEW = "/"

SECURITY_USERNAME_ENABLE = True
SECURITY_USERNAME_REQUIRED = True

SECURITY_TRACKABLE = True
SECURITY_CHANGEABLE = True
SECURITY_RECOVERABLE = True
SECURITY_REGISTERABLE = True
SECURITY_CONFIRMABLE = True
SECURITY_SEND_REGISTER_EMAIL = True

SECURITY_AUTO_LOGIN_AFTER_CONFIRM = True
SECURITY_LOGIN_WITHOUT_CONFIRMATION = False
SECURITY_PHONE_REGION_DEFAULT = "CL"
# Flask-Babel
BABEL_DEFAULT_LOCALE = "es"
BABEL_DEFAULT_TIMEZONE = "America/Santiago"
BABEL_DEFAULT_FOLDER = "store/translations"
BABEL_DOMAIN = "sabormirandiano"
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "es": {"flag": "mx", "name": "Español"},
}

# Flask Debugtoolbar
DEBUG_TB_ENABLED = False
DEBUG_TB_INTERCEPT_REDIRECTS = DEBUG
DEBUG_TB_PANELS = (
    "flask_debugtoolbar.panels.versions.VersionDebugPanel",
    "flask_debugtoolbar.panels.timer.TimerDebugPanel",
    "flask_debugtoolbar.panels.headers.HeaderDebugPanel",
    "flask_debugtoolbar.panels.request_vars.RequestVarsDebugPanel",
    "flask_debugtoolbar.panels.config_vars.ConfigVarsDebugPanel",
    "flask_debugtoolbar.panels.template.TemplateDebugPanel",
    "flask_debugtoolbar.panels.sqlalchemy.SQLAlchemyDebugPanel",
    "flask_debugtoolbar.panels.logger.LoggingPanel",
    "flask_debugtoolbar.panels.route_list.RouteListDebugPanel",
    "flask_debugtoolbar.panels.profiler.ProfilerDebugPanel",
    "flask_debugtoolbar.panels.g.GDebugPanel",
)
TEMPLATES_AUTO_RELOAD = True
EXPLAIN_TEMPLATE_LOADING = False


# Daleks mailer — HTTP service that delivers emails asynchronously.
# Override with FLASK_DALEKS_URL env var in production.
DALEKS_URL = "http://zvn-lin2.local:2525"

# Payment provider authentication
# These can be overridden by environment variables prefixed with FLASK_
# e.g. export FLASK_KHIPU_API_KEY=your-real-key
KHIPU_API_KEY = ""
# Merchant secret used to verify x-khipu-signature on incoming webhooks.
# e.g. export FLASK_KHIPU_WEBHOOK_SECRET=your-merchant-secret
KHIPU_WEBHOOK_SECRET = ""

# Public base URL (scheme + domain) used to build webhook URLs sent to
# payment providers.  Must be reachable from the internet.
# e.g. export FLASK_MERCHANTS_WEBHOOK_BASE_URL=https://pay.example.com
MERCHANTS_WEBHOOK_BASE_URL = ""

# UI display labels shown in the payment modal (modal-abono).
# Keys must match the provider key registered in flask_merchants.
# Falls back to provider.name / provider.description when a key is absent.
MERCHANTS_PROVIDER_LABELS = {
    "khipu": {
        "title": "Transferencia Electrónica",
        "subtitle": "Validación automática de abonos, procesado por Khipu",
    },
    "cafeteria": {
        "title": "Efectivo/Tarjetas",
        "subtitle": "Presencialmente en la Cafeteria del colegio",
    },
}

# STORE_SOCIALS = {
#     "youtube": "https://www.youtube.com/channel/channel-name",
#     "instagram": "https://www.instagram.com/instagram-user",
#     "facebook": "https://www.facebook.com/facebook-user",
# }
# STORE_BRAND_ICON = "bi bi-shop"
# STORE_NAME = "Storefront"

# ------------------------------------------------------------------
# Logging configuration
# ------------------------------------------------------------------
# Three facilities write rotating files to the logs/ directory:
#   sm.app    – logins, password changes, settings updates, app warnings
#   sm.celery – task lifecycle, connection errors
#   sm.audit  – payments, orders, pedidos, new users (audit trail)
#
# To override completely, set LOGGING to a full logging.config.dictConfig
# dict.  Individual file paths, levels, and retention can also be tuned via
# the scalar keys below without replacing the full dict.
#
# Scalar overrides (used only when LOGGING is not set):
APP_LOG_FILE = f"{BASE_DIR}/logs/app.log"
APP_LOG_LEVEL = LOG_LEVEL
APP_LOG_BACKUP_COUNT = 14

CELERY_LOG_FILE = f"{BASE_DIR}/logs/celery.log"
CELERY_LOG_LEVEL = LOG_LEVEL
CELERY_LOG_BACKUP_COUNT = 14

AUDIT_LOG_FILE = f"{BASE_DIR}/logs/audit.log"
AUDIT_LOG_LEVEL = "INFO"
AUDIT_LOG_BACKUP_COUNT = 30

# Full dictConfig example — uncomment and customise to take full control:
# LOGGING = {
#     "version": 1,
#     "disable_existing_loggers": False,
#     "formatters": {
#         "standard": {
#             "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
#             "datefmt": "%Y-%m-%d %H:%M:%S",
#         },
#     },
#     "handlers": {
#         "app_file": {
#             "class": "logging.handlers.TimedRotatingFileHandler",
#             "filename": f"{BASE_DIR}/logs/app.log",
#             "when": "midnight",
#             "backupCount": 14,
#             "encoding": "utf-8",
#             "formatter": "standard",
#         },
#         "celery_file": {
#             "class": "logging.handlers.TimedRotatingFileHandler",
#             "filename": f"{BASE_DIR}/logs/celery.log",
#             "when": "midnight",
#             "backupCount": 14,
#             "encoding": "utf-8",
#             "formatter": "standard",
#         },
#         "audit_file": {
#             "class": "logging.handlers.TimedRotatingFileHandler",
#             "filename": f"{BASE_DIR}/logs/audit.log",
#             "when": "midnight",
#             "backupCount": 30,
#             "encoding": "utf-8",
#             "formatter": "standard",
#         },
#     },
#     "loggers": {
#         "sm.app": {
#             "handlers": ["app_file"],
#             "level": "INFO",
#             "propagate": False,
#         },
#         "sm.celery": {
#             "handlers": ["celery_file"],
#             "level": "INFO",
#             "propagate": False,
#         },
#         "sm.audit": {
#             "handlers": ["audit_file"],
#             "level": "INFO",
#             "propagate": False,
#         },
#     },
# }

# Path shown in the admin dashboard audit panel (must match audit_file above)
AUDIT_LOG_PATH = f"{BASE_DIR}/logs/audit.log"

# ------------------------------------------------------------------
# School staff periodic email scheduler
# Runs are triggered on the first matching Flask request (no Celery Beat needed).
# ------------------------------------------------------------------

# Day of month (1-31) to send the monthly billing email.
# 0 (default) means the last day of each month.
STAFF_INFORME_MENSUAL_DIA: int = 0

# Hour (0-23, local time) at which the monthly email window opens.
STAFF_INFORME_MENSUAL_HORA: int = 8

# Weekday (0=Monday … 6=Sunday) to send the weekly standing-bill email.
STAFF_INFORME_SEMANAL_DIA: int = 0  # Monday

# Hour (0-23, local time) at which the weekly email window opens.
STAFF_INFORME_SEMANAL_HORA: int = 8
