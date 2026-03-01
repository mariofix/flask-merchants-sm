"""Tests for app/staff/scheduler.py.

Tests the request-based scheduler that fires the monthly and weekly
staff email tasks without Celery Beat.
"""

import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

TIMEZONE_SANTIAGO = ZoneInfo("America/Santiago")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_now(year, month, day, hour, weekday=None):
    """Return a datetime in Santiago timezone for the given values."""
    dt = datetime(year, month, day, hour, 0, tzinfo=TIMEZONE_SANTIAGO)
    return dt


# ---------------------------------------------------------------------------
# _last_day_of_month
# ---------------------------------------------------------------------------

class TestLastDayOfMonth:
    def test_february_non_leap(self):
        from app.staff.scheduler import _last_day_of_month
        from datetime import date
        assert _last_day_of_month(date(2025, 2, 1)) == 28

    def test_february_leap(self):
        from app.staff.scheduler import _last_day_of_month
        from datetime import date
        assert _last_day_of_month(date(2024, 2, 1)) == 29

    def test_january(self):
        from app.staff.scheduler import _last_day_of_month
        from datetime import date
        assert _last_day_of_month(date(2026, 1, 15)) == 31

    def test_april(self):
        from app.staff.scheduler import _last_day_of_month
        from datetime import date
        assert _last_day_of_month(date(2026, 4, 1)) == 30


# ---------------------------------------------------------------------------
# _check_informe_mensual
# ---------------------------------------------------------------------------

class TestCheckInformeMensual:
    def test_does_not_fire_on_wrong_day(self, app):
        """Should not fire when today's day != target day."""
        with app.app_context():
            app.config["STAFF_INFORME_MENSUAL_DIA"] = 1
            app.config["STAFF_INFORME_MENSUAL_HORA"] = 8
            # Simulate a request on the 15th - wrong day
            now = _make_now(2026, 3, 15, 9)
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.tasks.send_informe_mensual_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_mensual
                _check_informe_mensual()
                mock_task.delay.assert_not_called()

    def test_does_not_fire_before_target_hour(self, app):
        with app.app_context():
            app.config["STAFF_INFORME_MENSUAL_DIA"] = 31
            app.config["STAFF_INFORME_MENSUAL_HORA"] = 8
            now = _make_now(2026, 3, 31, 7)  # hour 7, target is 8
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.tasks.send_informe_mensual_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_mensual
                _check_informe_mensual()
                mock_task.delay.assert_not_called()

    def test_fires_on_correct_day_and_hour(self, db_session, app):
        with app.app_context():
            app.config["STAFF_INFORME_MENSUAL_DIA"] = 28
            app.config["STAFF_INFORME_MENSUAL_HORA"] = 8
            now = _make_now(2026, 2, 28, 9)
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.staff.scheduler._get_last_run", return_value=None), \
                 patch("app.staff.scheduler._set_last_run") as mock_set, \
                 patch("app.tasks.send_informe_mensual_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_mensual
                _check_informe_mensual()
                mock_task.delay.assert_called_once()
                mock_set.assert_called_once()

    def test_does_not_fire_twice_in_same_month(self, db_session, app):
        with app.app_context():
            app.config["STAFF_INFORME_MENSUAL_DIA"] = 28
            app.config["STAFF_INFORME_MENSUAL_HORA"] = 8
            now = _make_now(2026, 2, 28, 9)
            # Simulate last_run was already this month
            last_run = _make_now(2026, 2, 28, 8)
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.staff.scheduler._get_last_run", return_value=last_run), \
                 patch("app.tasks.send_informe_mensual_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_mensual
                _check_informe_mensual()
                mock_task.delay.assert_not_called()

    def test_last_day_of_month_default(self, db_session, app):
        """With DIA=0, should fire on the last day of the month."""
        with app.app_context():
            app.config["STAFF_INFORME_MENSUAL_DIA"] = 0  # last day
            app.config["STAFF_INFORME_MENSUAL_HORA"] = 8
            now = _make_now(2026, 3, 31, 9)  # March 31 = last day
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.staff.scheduler._get_last_run", return_value=None), \
                 patch("app.staff.scheduler._set_last_run"), \
                 patch("app.tasks.send_informe_mensual_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_mensual
                _check_informe_mensual()
                mock_task.delay.assert_called_once()


# ---------------------------------------------------------------------------
# _check_informe_semanal
# ---------------------------------------------------------------------------

class TestCheckInformeSemanal:
    def test_does_not_fire_on_wrong_weekday(self, app):
        with app.app_context():
            app.config["STAFF_INFORME_SEMANAL_DIA"] = 0  # Monday
            app.config["STAFF_INFORME_SEMANAL_HORA"] = 8
            # 2026-02-24 is a Tuesday (weekday=1)
            now = _make_now(2026, 2, 24, 9)
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.tasks.send_informe_semanal_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_semanal
                _check_informe_semanal()
                mock_task.delay.assert_not_called()

    def test_fires_on_correct_weekday_and_hour(self, db_session, app):
        with app.app_context():
            app.config["STAFF_INFORME_SEMANAL_DIA"] = 0  # Monday
            app.config["STAFF_INFORME_SEMANAL_HORA"] = 8
            # 2026-02-23 is a Monday (weekday=0)
            now = _make_now(2026, 2, 23, 9)
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.staff.scheduler._get_last_run", return_value=None), \
                 patch("app.staff.scheduler._set_last_run") as mock_set, \
                 patch("app.tasks.send_informe_semanal_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_semanal
                _check_informe_semanal()
                mock_task.delay.assert_called_once()
                mock_set.assert_called_once()

    def test_does_not_fire_within_7_days_of_last_run(self, db_session, app):
        with app.app_context():
            app.config["STAFF_INFORME_SEMANAL_DIA"] = 0
            app.config["STAFF_INFORME_SEMANAL_HORA"] = 8
            now = _make_now(2026, 2, 23, 9)
            last_run = _make_now(2026, 2, 20, 8)  # 3 days ago < 7
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.staff.scheduler._get_last_run", return_value=last_run), \
                 patch("app.tasks.send_informe_semanal_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_semanal
                _check_informe_semanal()
                mock_task.delay.assert_not_called()

    def test_fires_after_7_days_since_last_run(self, db_session, app):
        with app.app_context():
            app.config["STAFF_INFORME_SEMANAL_DIA"] = 0
            app.config["STAFF_INFORME_SEMANAL_HORA"] = 8
            now = _make_now(2026, 2, 23, 9)
            last_run = _make_now(2026, 2, 16, 8)  # exactly 7 days ago
            with patch("app.staff.scheduler.datetime") as mock_dt, \
                 patch("app.staff.scheduler._get_last_run", return_value=last_run), \
                 patch("app.staff.scheduler._set_last_run"), \
                 patch("app.tasks.send_informe_semanal_staff") as mock_task:
                mock_dt.now.return_value = now
                from app.staff.scheduler import _check_informe_semanal
                _check_informe_semanal()
                mock_task.delay.assert_called_once()


# ---------------------------------------------------------------------------
# check_and_fire_staff_jobs (integration: catches exceptions)
# ---------------------------------------------------------------------------

class TestCheckAndFireStaffJobs:
    def test_does_not_raise_on_exception(self, app):
        """Scheduler errors must never break a user request."""
        with app.app_context():
            with patch("app.staff.scheduler._check_informe_mensual", side_effect=RuntimeError("boom")):
                from app.staff.scheduler import check_and_fire_staff_jobs
                check_and_fire_staff_jobs()  # must not raise
