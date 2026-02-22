from flask import Blueprint, abort, render_template
from .model import MenuDiario, Settings
from .database import db
from datetime import date, datetime, time
from collections import OrderedDict
from zoneinfo import ZoneInfo
from sqlalchemy import and_, or_, select
from flask_login import login_required
from flask_security.decorators import roles_required
from types import SimpleNamespace
import locale

TIMEZONE_SANTIAGO = ZoneInfo("America/Santiago")
SLUG_REZAGADOS = "menu-rezagados"
DESCRIPCION_REZAGADOS = "Menú Rezagados"


def get_casino_timelimits():
    """Load casino time limits and virtual menu config from Settings (slug='casino_timelimits').

    Returns (hora_limite_pedido, hora_limite_rezagados, menu_rezagados_cfg).

    ``menu_rezagados_cfg`` is a dict with keys ``slug``, ``descripcion``, and ``precio``.
    All values fall back to safe defaults when the Settings row is absent.

    Expected Settings value shape::

        {
            "hora_limite_pedido":  "10:00",
            "hora_limite_rezagados": "14:00",
            "menu_rezagados": {
                "slug":        "menu-rezagados",
                "descripcion": "Menú Rezagados",
                "precio":      3000
            }
        }
    """

    def _parse_time(s, default):
        try:
            h, m = map(int, str(s).split(":"))
            return time(h, m)
        except (AttributeError, ValueError):
            return default

    settings = db.session.execute(db.select(Settings).filter_by(slug="casino_timelimits")).scalar_one_or_none()
    v = (settings.value or {}) if settings else {}

    hora_limite = _parse_time(v.get("hora_limite_pedido", "10:00"), time(10, 0))
    hora_rezagados = _parse_time(v.get("hora_limite_rezagados", "14:00"), time(14, 0))

    mr = v.get("menu_rezagados") or {}
    try:
        precio_rezagados = int(mr.get("precio", 3000))
    except (TypeError, ValueError):
        precio_rezagados = 3000
    menu_rezagados_cfg = {
        "slug": mr.get("slug", SLUG_REZAGADOS),
        "descripcion": mr.get("descripcion", DESCRIPCION_REZAGADOS),
        "precio": precio_rezagados,
    }

    return hora_limite, hora_rezagados, menu_rezagados_cfg

core_bp = Blueprint("core", __name__)


@core_bp.route("/", methods=["GET"])
def index():
    today = date.today()

    stmt = select(MenuDiario.dia).where(MenuDiario.dia >= today).distinct().order_by(MenuDiario.dia.asc()).limit(5)

    lista_dias = db.session.execute(stmt).scalars().all()
    payload = OrderedDict()
    payload_dias = OrderedDict()
    for dia in lista_dias:
        payload[dia.isoformat()] = obtiene_menues(dia.isoformat())

        locale.setlocale(locale.LC_TIME, "es_CL.utf8")
        payload_dias[dia.isoformat()] = dia.strftime("%A, %d de %B de %Y")

    return render_template("site/index.j2", menues=payload, str_dias=payload_dias)


@core_bp.route("/admin", methods=["GET"])
@roles_required("admin")
def admin():
    return render_template("seleccion.html")


@core_bp.route("/aiuda", methods=["GET"])
def ayuda():
    return render_template("core/ayuda.html")


def obtiene_menues(dia):

    if dia:
        try:
            fecha = datetime.strptime(dia, "%Y-%m-%d").date()
        except ValueError:
            return None
    else:
        fecha = date.today()

    menu_hoy = MenuDiario.query.filter(
        or_(MenuDiario.dia == fecha, MenuDiario.es_permanente == True),
        and_(MenuDiario.activo == True),
    ).all()
    return menu_hoy


@core_bp.route("/consulta/<dia>")
@login_required
def consulta(dia):
    try:
        fecha = datetime.strptime(dia, "%Y-%m-%d").date()
    except ValueError:
        abort(404)

    hora_limite, hora_rezagados, menu_rezagados_cfg = get_casino_timelimits()
    ahora = datetime.now(TIMEZONE_SANTIAGO).time()
    today = datetime.now(TIMEZONE_SANTIAGO).date()

    # Past dates are not available for ordering
    if fecha < today:
        abort(404)

    if fecha == today:
        if ahora >= hora_rezagados:
            # After 14:00 — today is closed, order for next day instead
            abort(404)
        elif ahora >= hora_limite:
            # Between 10:00–14:00 — only the configured virtual menu is available
            menu_rezagados = SimpleNamespace(
                slug=menu_rezagados_cfg["slug"],
                descripcion=menu_rezagados_cfg["descripcion"],
                precio=menu_rezagados_cfg["precio"],
                entradas=[],
                postres=[],
            )
            return render_template(
                "casino/form_menu.html",
                menues=[menu_rezagados],
                dia=dia,
                es_rezagados=True,
            )

    menues = obtiene_menues(dia)
    if not menues:
        abort(404)

    return render_template("casino/form_menu.html", menues=menues, dia=dia)
