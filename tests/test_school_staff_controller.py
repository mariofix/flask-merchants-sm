"""Tests for SchoolStaffController.

Covers every public method.  Pure methods (no DB) are tested without
fixtures; DB-dependent methods use the session fixture from conftest.
"""

import uuid
from decimal import Decimal

import pytest

from app.staff.controller import SchoolStaffController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctrl():
    return SchoolStaffController()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_staff_user(db_session):
    """A minimal User row for a school staff member."""
    from app.model import User
    user = User()
    user.email = "staff@test.cl"
    user.username = "staff_test"
    user.password = "password"
    user.active = True
    user.fs_uniquifier = str(uuid.uuid4())
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def sample_staff(db_session, sample_staff_user):
    """A SchoolStaff linked to *sample_staff_user*."""
    from app.model import SchoolStaff
    staff = SchoolStaff()
    staff.nombre = "Ana Docente"
    staff.usuario = sample_staff_user
    staff.limite_cuenta = 50000
    db_session.add(staff)
    db_session.commit()
    return staff


# ---------------------------------------------------------------------------
# get_staff
# ---------------------------------------------------------------------------

class TestGetStaff:
    def test_returns_none_when_no_profile(self, db_session, sample_staff_user):
        from app.model import SchoolStaff
        db_session.execute(SchoolStaff.__table__.delete())
        db_session.commit()
        assert make_ctrl().get_staff(sample_staff_user) is None

    def test_returns_profile_for_linked_user(self, db_session, sample_staff):
        result = make_ctrl().get_staff(sample_staff.usuario)
        assert result is not None
        assert result.id == sample_staff.id


# ---------------------------------------------------------------------------
# create_staff
# ---------------------------------------------------------------------------

class TestCreateStaff:
    def test_creates_and_persists_record(self, db_session, sample_staff_user):
        staff = make_ctrl().create_staff("Pedro Limpieza", user=sample_staff_user)
        assert staff.id is not None
        assert staff.nombre == "Pedro Limpieza"
        assert staff.usuario_id == sample_staff_user.id

    def test_creates_with_limite_cuenta(self, db_session, sample_staff_user):
        staff = make_ctrl().create_staff("Ana Admin", user=sample_staff_user, limite_cuenta=30000)
        assert staff.limite_cuenta == 30000

    def test_creates_unlimited_when_no_limit(self, db_session, sample_staff_user):
        staff = make_ctrl().create_staff("Sin Límite", user=sample_staff_user)
        assert staff.limite_cuenta is None


# ---------------------------------------------------------------------------
# get_deuda_actual
# ---------------------------------------------------------------------------

class TestGetDeudaActual:
    def test_zero_when_no_pedidos(self, db_session, sample_staff):
        deuda = make_ctrl().get_deuda_actual(sample_staff)
        assert deuda == Decimal(0)

    def test_sums_unpaid_pedidos(self, db_session, sample_staff):
        from app.model import SchoolStaffPedido, EstadoPedido
        p1 = SchoolStaffPedido()
        p1.staff_id = sample_staff.id
        p1.precio_total = Decimal(5000)
        p1.pagado = False
        p1.estado = EstadoPedido.CREADO
        db_session.add(p1)
        p2 = SchoolStaffPedido()
        p2.staff_id = sample_staff.id
        p2.precio_total = Decimal(3000)
        p2.pagado = False
        p2.estado = EstadoPedido.CREADO
        db_session.add(p2)
        db_session.commit()
        deuda = make_ctrl().get_deuda_actual(sample_staff)
        assert deuda == Decimal(8000)

    def test_excludes_paid_pedidos(self, db_session, sample_staff):
        from app.model import SchoolStaffPedido, EstadoPedido
        p = SchoolStaffPedido()
        p.staff_id = sample_staff.id
        p.precio_total = Decimal(4000)
        p.pagado = True
        p.estado = EstadoPedido.PAGADO
        db_session.add(p)
        db_session.commit()
        deuda = make_ctrl().get_deuda_actual(sample_staff)
        assert deuda == Decimal(0)

    def test_excludes_cancelled_pedidos(self, db_session, sample_staff):
        from app.model import SchoolStaffPedido, EstadoPedido
        p = SchoolStaffPedido()
        p.staff_id = sample_staff.id
        p.precio_total = Decimal(2000)
        p.pagado = False
        p.estado = EstadoPedido.CANCELADA
        db_session.add(p)
        db_session.commit()
        deuda = make_ctrl().get_deuda_actual(sample_staff)
        assert deuda == Decimal(0)


# ---------------------------------------------------------------------------
# puede_comprar
# ---------------------------------------------------------------------------

class TestPuedeComprar:
    def test_unlimited_always_returns_true(self, db_session, sample_staff_user):
        staff = make_ctrl().create_staff("Unlimited", user=sample_staff_user, limite_cuenta=None)
        assert make_ctrl().puede_comprar(staff, Decimal(999999)) is True

    def test_within_limit_returns_true(self, db_session, sample_staff):
        # No existing debt, limit is 50000
        assert make_ctrl().puede_comprar(sample_staff, Decimal(49000)) is True

    def test_over_limit_returns_false(self, db_session, sample_staff):
        from app.model import SchoolStaffPedido, EstadoPedido
        # Add debt of 45000, limit is 50000 — can't add 10000 more
        p = SchoolStaffPedido()
        p.staff_id = sample_staff.id
        p.precio_total = Decimal(45000)
        p.pagado = False
        p.estado = EstadoPedido.CREADO
        db_session.add(p)
        db_session.commit()
        assert make_ctrl().puede_comprar(sample_staff, Decimal(10000)) is False

    def test_exact_limit_boundary_returns_true(self, db_session, sample_staff):
        # No debt, limit is 50000, buying exactly 50000 should work
        assert make_ctrl().puede_comprar(sample_staff, Decimal(50000)) is True


# ---------------------------------------------------------------------------
# update_ajustes
# ---------------------------------------------------------------------------

class TestUpdateAjustes:
    def test_updates_nombre_and_informe_semanal(self, db_session, sample_staff):
        user = sample_staff.usuario
        make_ctrl().update_ajustes(sample_staff, user, {
            "nombre": "Nuevo Nombre",
            "informe_semanal": "on",
        })
        db_session.refresh(sample_staff)
        assert sample_staff.nombre == "Nuevo Nombre"
        assert sample_staff.informe_semanal is True

    def test_disables_informe_semanal_when_not_present(self, db_session, sample_staff):
        sample_staff.informe_semanal = True
        db_session.commit()
        make_ctrl().update_ajustes(sample_staff, sample_staff.usuario, {})
        db_session.refresh(sample_staff)
        assert sample_staff.informe_semanal is False

    def test_updates_user_phone(self, db_session, sample_staff):
        user = sample_staff.usuario
        make_ctrl().update_ajustes(sample_staff, user, {"phone": "+56987654321"})
        db_session.refresh(user)
        assert user.username == "+56987654321"


# ---------------------------------------------------------------------------
# crea_pedido
# ---------------------------------------------------------------------------

class TestCreaPedido:
    def test_returns_string_codigo(self, db_session, sample_staff):
        payload = [{"slug": "menu-lunes", "date": "2026-03-01", "note": "", "alumnos": []}]
        codigo = make_ctrl().crea_pedido(payload, staff_id=sample_staff.id)
        assert isinstance(codigo, str)
        assert len(codigo) == 36

    def test_links_staff(self, db_session, sample_staff):
        from app.database import db
        from app.model import SchoolStaffPedido
        payload = [{"slug": "menu-martes", "date": "2026-03-02", "note": "", "alumnos": []}]
        codigo = make_ctrl().crea_pedido(payload, staff_id=sample_staff.id)
        pedido = db_session.execute(
            db.select(SchoolStaffPedido).filter_by(codigo=codigo)
        ).scalar_one()
        assert pedido.staff_id == sample_staff.id


# ---------------------------------------------------------------------------
# get_pedidos
# ---------------------------------------------------------------------------

class TestGetPedidos:
    def test_returns_empty_list_when_no_pedidos(self, db_session, sample_staff):
        result = make_ctrl().get_pedidos(sample_staff)
        assert result == []

    def test_returns_pedido_info_dicts(self, db_session, sample_staff):
        payload = [{"slug": "menu-lunes", "date": "2026-03-01", "note": "", "alumnos": []}]
        make_ctrl().crea_pedido(payload, staff_id=sample_staff.id)
        result = make_ctrl().get_pedidos(sample_staff)
        assert len(result) == 1
        assert "pedido" in result[0]
        assert "pago" in result[0]
