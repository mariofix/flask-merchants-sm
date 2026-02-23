"""Tests for ApoderadoController.

Covers every public method.  Pure methods (no DB) are tested without
fixtures; DB-dependent methods use the session fixture from conftest.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.apoderado.controller import ApoderadoController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctrl():
    return ApoderadoController()


# ---------------------------------------------------------------------------
# get_apoderado
# ---------------------------------------------------------------------------

class TestGetApoderado:
    def test_returns_none_when_no_profile(self, db_session, sample_user):
        # sample_user exists but has no Apoderado yet
        from app.model import Apoderado
        db_session.execute(Apoderado.__table__.delete())
        db_session.commit()
        assert make_ctrl().get_apoderado(sample_user) is None

    def test_returns_profile_for_linked_user(self, db_session, sample_apoderado):
        result = make_ctrl().get_apoderado(sample_apoderado.usuario)
        assert result is not None
        assert result.id == sample_apoderado.id


# ---------------------------------------------------------------------------
# create_apoderado
# ---------------------------------------------------------------------------

class TestCreateApoderado:
    def test_creates_and_persists_record(self, db_session, sample_user):
        ctrl = make_ctrl()
        apoderado = ctrl.create_apoderado("Pedro Soto", alumnos_count=2, user=sample_user)
        assert apoderado.id is not None
        assert apoderado.nombre == "Pedro Soto"
        assert apoderado.alumnos_registro == 2
        assert apoderado.usuario_id == sample_user.id

    def test_alumnos_count_cast_to_int(self, db_session, sample_user):
        apoderado = make_ctrl().create_apoderado("Ana", alumnos_count="3", user=sample_user)
        assert apoderado.alumnos_registro == 3


# ---------------------------------------------------------------------------
# create_alumnos
# ---------------------------------------------------------------------------

class TestCreateAlumnos:
    def test_creates_correct_number_of_alumnos(self, db_session, sample_apoderado):
        ctrl = make_ctrl()
        initial = len(sample_apoderado.alumnos)
        ctrl.create_alumnos(sample_apoderado, [
            {"nombre": "Sofía", "curso": "3B", "edad": "9", "restricciones": []},
            {"nombre": "Diego", "curso": "4A", "edad": "10", "restricciones": []},
        ])
        db_session.refresh(sample_apoderado)
        assert len(sample_apoderado.alumnos) == initial + 2

    def test_restricciones_are_stored(self, db_session, sample_apoderado):
        restricciones = [{"nombre": "Maní", "motivo": "Alergia"}]
        make_ctrl().create_alumnos(sample_apoderado, [
            {"nombre": "Laura", "curso": "2A", "edad": "8", "restricciones": restricciones},
        ])
        db_session.refresh(sample_apoderado)
        nuevo = next(a for a in sample_apoderado.alumnos if a.nombre == "Laura")
        assert nuevo.restricciones == restricciones


# ---------------------------------------------------------------------------
# update_preferences
# ---------------------------------------------------------------------------

class TestUpdatePreferences:
    def test_applies_all_fields(self, db_session, sample_apoderado):
        make_ctrl().update_preferences(sample_apoderado, {
            "notificacion_comprobante": True,
            "notificacion_compra": True,
            "informe_semanal": False,
            "tag_compartido": False,
            "correo_alternativo": "otro@test.cl",
            "monto_diario": "5000",
            "monto_semanal": "20000",
            "limite_notificaciones": "2000",
        })
        db_session.refresh(sample_apoderado)
        assert sample_apoderado.comprobantes_transferencia is True
        assert sample_apoderado.notificacion_compra is True
        assert sample_apoderado.copia_notificaciones == "otro@test.cl"
        assert sample_apoderado.maximo_diario == 5000
        assert sample_apoderado.maximo_semanal == 20000
        assert sample_apoderado.limite_notificacion == 2000
        assert sample_apoderado.saldo_cuenta == 0

    def test_cascades_limits_to_alumnos(self, db_session, sample_apoderado):
        make_ctrl().update_preferences(sample_apoderado, {
            "monto_diario": "3000",
            "monto_semanal": "12000",
            "limite_notificaciones": "1500",
        })
        for alumno in sample_apoderado.alumnos:
            assert alumno.maximo_diario == 3000
            assert alumno.maximo_semanal == 12000


# ---------------------------------------------------------------------------
# create_abono
# ---------------------------------------------------------------------------

class TestCreateAbono:
    def test_creates_abono_record(self, db_session, sample_apoderado):
        abono = make_ctrl().create_abono(sample_apoderado, Decimal("10000"), "cafeteria")
        assert abono.id is not None
        assert abono.monto == Decimal("10000")
        assert abono.forma_pago == "cafeteria"
        assert abono.descripcion == "Abono Web"
        assert abono.apoderado_id == sample_apoderado.id

    def test_codigo_is_unique(self, db_session, sample_apoderado):
        ctrl = make_ctrl()
        a1 = ctrl.create_abono(sample_apoderado, Decimal("1000"), "cafeteria")
        a2 = ctrl.create_abono(sample_apoderado, Decimal("2000"), "cafeteria")
        assert a1.codigo != a2.codigo


# ---------------------------------------------------------------------------
# get_abono
# ---------------------------------------------------------------------------

class TestGetAbono:
    def test_returns_none_tuple_for_unknown_codigo(self, db_session, app):
        abono, pago, display_code = make_ctrl().get_abono("nonexistent-uuid")
        assert abono is None
        assert pago is None
        assert display_code == ""

    def test_returns_abono_when_found(self, db_session, sample_apoderado):
        created = make_ctrl().create_abono(sample_apoderado, Decimal("5000"), "cafeteria")
        abono, pago, display_code = make_ctrl().get_abono(created.codigo)
        assert abono is not None
        assert abono.codigo == created.codigo
        assert pago is None        # no Payment row linked yet
        assert display_code == ""


# ---------------------------------------------------------------------------
# get_spending_stats
# ---------------------------------------------------------------------------

class TestGetSpendingStats:
    def test_returns_dict_keyed_by_alumno_id(self, db_session, sample_apoderado):
        stats = make_ctrl().get_spending_stats(sample_apoderado)
        for alumno in sample_apoderado.alumnos:
            assert alumno.id in stats
            assert "gasto_hoy" in stats[alumno.id]
            assert "gasto_semana" in stats[alumno.id]

    def test_zeroes_when_no_orders(self, db_session, sample_apoderado):
        stats = make_ctrl().get_spending_stats(sample_apoderado)
        for v in stats.values():
            assert v["gasto_hoy"] == 0
            assert v["gasto_semana"] == 0


# ---------------------------------------------------------------------------
# get_alumno_spending
# ---------------------------------------------------------------------------

class TestGetAlumnoSpending:
    def test_returns_expected_keys(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        result = make_ctrl().get_alumno_spending(alumno)
        assert set(result.keys()) == {"uso_24h", "uso_7d", "uso_14d"}

    def test_zeroes_when_no_orders(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        result = make_ctrl().get_alumno_spending(alumno)
        assert result["uso_24h"] == 0
        assert result["uso_7d"] == 0
        assert result["uso_14d"] == 0


# ---------------------------------------------------------------------------
# update_ajustes
# ---------------------------------------------------------------------------

class TestUpdateAjustes:
    def test_updates_apoderado_fields(self, db_session, sample_apoderado):
        user = sample_apoderado.usuario
        make_ctrl().update_ajustes(sample_apoderado, user, {
            "nombre": "Nuevo Nombre",
            "notificacion_compra": "on",
            "maximo_diario": "4000",
        })
        db_session.refresh(sample_apoderado)
        assert sample_apoderado.nombre == "Nuevo Nombre"
        assert sample_apoderado.notificacion_compra is True
        assert sample_apoderado.maximo_diario == 4000

    def test_updates_user_phone(self, db_session, sample_apoderado):
        user = sample_apoderado.usuario
        make_ctrl().update_ajustes(sample_apoderado, user, {"phone": "+56912345678"})
        db_session.refresh(user)
        assert user.username == "+56912345678"

    def test_none_apoderado_does_not_raise(self, db_session, sample_user):
        # Should update only the user without crashing
        make_ctrl().update_ajustes(None, sample_user, {"phone": "+56999999999"})
        db_session.refresh(sample_user)
        assert sample_user.username == "+56999999999"


# ---------------------------------------------------------------------------
# crea_orden
# ---------------------------------------------------------------------------

class TestCreaOrden:
    def test_returns_string_codigo(self, db_session, app):
        payload = [{"slug": "menu-lunes", "date": "2026-03-01", "note": "", "alumnos": []}]
        codigo = make_ctrl().crea_orden(payload)
        assert isinstance(codigo, str)
        assert len(codigo) == 36  # UUID format

    def test_links_apoderado_when_provided(self, db_session, sample_apoderado):
        from app.database import db
        from app.model import Pedido
        payload = [{"slug": "menu-lunes", "date": "2026-03-01", "note": "", "alumnos": []}]
        codigo = make_ctrl().crea_orden(payload, apoderado_id=sample_apoderado.id)
        pedido = db_session.execute(
            db.select(Pedido).filter_by(codigo=codigo)
        ).scalar_one()
        assert pedido.apoderado_id == sample_apoderado.id


# ---------------------------------------------------------------------------
# compute_advertencias  (pure — no DB needed)
# ---------------------------------------------------------------------------

class TestComputeAdvertencias:
    def setup_method(self):
        self.ctrl = make_ctrl()

    def _make_menu(self, *, alergenos=False, vegano=False, vegetariano=False):
        plato = SimpleNamespace(
            contiene_alergenos=alergenos, es_vegano=vegano, es_vegetariano=vegetariano
        )
        opcion = SimpleNamespace(plato=plato)
        return SimpleNamespace(opciones=[opcion])

    def _make_alumno(self, nombre, restricciones):
        return SimpleNamespace(nombre=nombre, restricciones=restricciones)

    def test_virtual_menu_without_opciones_returns_empty(self):
        menu = SimpleNamespace(slug="menu-rezagados")  # no 'opciones'
        result = self.ctrl.compute_advertencias(menu, [])
        assert result == []

    def test_no_restrictions_returns_empty(self):
        menu = self._make_menu(alergenos=True)
        alumno = self._make_alumno("Juan", [])
        assert self.ctrl.compute_advertencias(menu, [alumno]) == []

    def test_allergy_on_alergenic_menu_returns_warning(self):
        menu = self._make_menu(alergenos=True)
        alumno = self._make_alumno("Ana", [{"nombre": "Maní", "motivo": "Alergia"}])
        result = self.ctrl.compute_advertencias(menu, [alumno])
        assert len(result) == 1
        assert result[0]["tipo"] == "warning"
        assert "Ana" in result[0]["alumno"]
        assert "Maní" in result[0]["mensaje"]

    def test_vegan_restriction_on_vegan_menu_returns_info(self):
        menu = self._make_menu(vegano=True)
        alumno = self._make_alumno("Luis", [{"nombre": "Vegano", "motivo": "Preferencia"}])
        result = self.ctrl.compute_advertencias(menu, [alumno])
        assert len(result) == 1
        assert result[0]["tipo"] == "info"

    def test_vegetarian_restriction_on_vegetarian_menu(self):
        menu = self._make_menu(vegetariano=True)
        alumno = self._make_alumno("Rosa", [{"nombre": "Vegetariano", "motivo": "Preferencia"}])
        result = self.ctrl.compute_advertencias(menu, [alumno])
        assert len(result) == 1
        assert result[0]["tipo"] == "info"

    def test_duplicates_are_removed(self):
        menu = self._make_menu(alergenos=True)
        alumno = self._make_alumno("Pedro", [
            {"nombre": "Maní", "motivo": "Alergia"},
            {"nombre": "Maní", "motivo": "Alergia"},  # duplicate
        ])
        result = self.ctrl.compute_advertencias(menu, [alumno])
        assert len(result) == 1

    def test_non_list_restricciones_are_skipped(self):
        menu = self._make_menu(alergenos=True)
        alumno = self._make_alumno("Marta", restricciones="not a list")
        assert self.ctrl.compute_advertencias(menu, [alumno]) == []

    def test_string_items_in_restricciones_are_skipped(self):
        menu = self._make_menu(alergenos=True)
        alumno = self._make_alumno("Carlos", restricciones=["Alergia", "Vegano"])
        assert self.ctrl.compute_advertencias(menu, [alumno]) == []

    def test_mixed_restricciones_processes_valid_dicts(self):
        menu = self._make_menu(alergenos=True)
        alumno = self._make_alumno("Ines", restricciones=[{"nombre": "Gluten", "motivo": "Alergia"}, "invalid_string"])
        result = self.ctrl.compute_advertencias(menu, [alumno])
        assert len(result) == 1
        assert result[0]["tipo"] == "warning"
        assert "Gluten" in result[0]["mensaje"]
