"""Request-based scheduler for school staff periodic email jobs.

On every Flask request, ``check_and_fire_staff_jobs`` is called.  It checks
whether the monthly billing email or the weekly standing-bill email is due,
fires the matching Celery task, and records the run time in the ``Settings``
table so it does not fire again in the same window.

Configuration (all optional - safe defaults are used when absent):

``STAFF_INFORME_MENSUAL_DIA``
    Day-of-month (int, 1-31) on which the monthly billing email is sent.
    Defaults to the last day of each month (``0``).  Set to e.g. ``28`` to
    always send on the 28th.

``STAFF_INFORME_MENSUAL_HORA``
    Hour (int, 0-23) at which the monthly email window opens.  Defaults to
    ``8`` (08:00).

``STAFF_INFORME_SEMANAL_DIA``
    Weekday (int, 0=Monday … 6=Sunday) on which the weekly email is sent.
    Defaults to ``0`` (Monday).

``STAFF_INFORME_SEMANAL_HORA``
    Hour (int, 0-23) at which the weekly email window opens.  Defaults to
    ``8`` (08:00).
"""

import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import current_app

TIMEZONE_SANTIAGO = ZoneInfo("America/Santiago")

_SLUG_MENSUAL = "staff_informe_mensual_last_run"
_SLUG_SEMANAL = "staff_informe_semanal_last_run"


def _last_day_of_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _get_last_run(slug: str) -> datetime | None:
    """Return the last-run datetime stored in Settings, or None."""
    from ..database import db
    from ..model import Settings

    row = db.session.execute(db.select(Settings).filter_by(slug=slug)).scalar_one_or_none()
    if row and row.value and row.value.get("last_run"):
        try:
            return datetime.fromisoformat(row.value["last_run"])
        except (ValueError, TypeError):
            return None
    return None


def _set_last_run(slug: str, dt: datetime) -> None:
    """Persist the last-run datetime into Settings."""
    from ..database import db
    from ..model import Settings

    row = db.session.execute(db.select(Settings).filter_by(slug=slug)).scalar_one_or_none()
    if row is None:
        row = Settings()
        row.slug = slug
        db.session.add(row)
    row.value = {"last_run": dt.isoformat()}
    db.session.commit()


def check_and_fire_staff_jobs() -> None:
    """Check if any periodic staff email job is due and fire it.

    Safe to call on every request - exits quickly when nothing is due.
    Catches all exceptions so a scheduler error never breaks a user request.
    """
    try:
        _check_informe_mensual()
        _check_informe_semanal()
    except Exception:  # pragma: no cover
        current_app.logger.exception("staff scheduler error")


def _check_informe_mensual() -> None:
    cfg = current_app.config
    now = datetime.now(TIMEZONE_SANTIAGO)
    today = now.date()

    target_dia = cfg.get("STAFF_INFORME_MENSUAL_DIA", 0)  # 0 = last day of month
    target_hora = int(cfg.get("STAFF_INFORME_MENSUAL_HORA", 8))

    if target_dia == 0:
        target_dia = _last_day_of_month(today)

    if today.day != target_dia:
        return
    if now.hour < target_hora:
        return

    last_run = _get_last_run(_SLUG_MENSUAL)
    if last_run and last_run.year == today.year and last_run.month == today.month:
        return  # already ran this month

    from ..tasks import send_informe_mensual_staff
    send_informe_mensual_staff()
    _set_last_run(_SLUG_MENSUAL, now)
    current_app.logger.info("staff_scheduler: dispatched send_informe_mensual_staff")


def _check_informe_semanal() -> None:
    cfg = current_app.config
    now = datetime.now(TIMEZONE_SANTIAGO)
    today = now.date()

    target_weekday = int(cfg.get("STAFF_INFORME_SEMANAL_DIA", 0))  # 0 = Monday
    target_hora = int(cfg.get("STAFF_INFORME_SEMANAL_HORA", 8))

    if today.weekday() != target_weekday:
        return
    if now.hour < target_hora:
        return

    last_run = _get_last_run(_SLUG_SEMANAL)
    if last_run:
        days_since = (today - last_run.date()).days
        if days_since < 7:
            return  # already ran this week

    from ..tasks import send_informe_semanal_staff
    send_informe_semanal_staff()
    _set_last_run(_SLUG_SEMANAL, now)
    current_app.logger.info("staff_scheduler: dispatched send_informe_semanal_staff")
