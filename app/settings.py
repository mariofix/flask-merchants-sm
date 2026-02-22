from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY: str
DEBUG = True
LOG_LEVEL = "DEBUG" if DEBUG else "INFO"
TRUSTED_HOSTS = ["tardis.local", "192.168.110.133"]
SESSION_COOKIE_NAME = "merchants"
DIRECTORIO_FOTOS_PLATO = f"{BASE_DIR}/app/static/platos"

SQLALCHEMY_DATABASE_URI = ""
SQLALCHEMY_RECORD_QUERIES = DEBUG
SQLALCHEMY_ECHO = False
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 1800}

SECURITY_EMAIL_SUBJECT_REGISTER = "Bienvenida a Sabor Mirandiano"
SECURITY_EMAIL_SENDER = "Sabor Mirandiano"
SECURITY_PASSWORD_SALT = "password-salt-randomnesssss.0"
SECURITY_POST_LOGIN_VIEW = "/apoderado/"
SECURITY_POST_LOGOUT_VIEW = "/"
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
BABEL_DOMAIN = "merchants"
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "es": {"flag": "mx", "name": "Español"},
}

# Flask Debugtoolbar
DEBUG_TB_ENABLED = DEBUG
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


# Flask-Mailman
MAIL_SERVER = ""
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
MAIL_TIMEOUT = 5
MAIL_USE_LOCALTIME = True

# Payment provider authentication
# These can be overridden by environment variables prefixed with FLASK_
# e.g. export FLASK_KHIPU_API_KEY=your-real-key
KHIPU_API_KEY = ""

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

CELERY = {
    "broker_url": "redis://10.100.254.2/10",
    "result_backend": "redis://10.100.254.2/11",
    "task_ignore_result": False,
    "worker_concurrency": 1,
    "worker_max_tasks_per_child": 1,
}
