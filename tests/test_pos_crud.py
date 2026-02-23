"""Tests for PosController (app/pos/crud.py).

Covers every public method using the shared fixtures from conftest.py.
Pure methods (no DB) are tested without fixtures; DB-dependent methods
use the session fixture.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.pos.crud import PosController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctrl():
    return PosController()


def _create_orden_casino(db_session, alumno, estado, fecha=None):
    """Create an OrdenCasino row for testing."""
    from app.model import EstadoAlmuerzo, OrdenCasino
    orden = OrdenCasino()
    orden.pedido_codigo = f"test-{uuid.uuid4()}"
    orden.alumno_id = alumno.id
    orden.menu_slug = "menu-test"
    orden.menu_descripcion = "Menú de Prueba"
    orden.menu_precio = Decimal("4000")
    orden.fecha = fecha or date.today()
    orden.estado = estado
    db_session.add(orden)
    db_session.commit()
    return orden


# ---------------------------------------------------------------------------
# get_alumnos_sin_tag
# ---------------------------------------------------------------------------

class TestGetAlumnosSinTag:
    def test_returns_alumno_without_tag(self, db_session, sample_apoderado):
        alumnos = make_ctrl().get_alumnos_sin_tag()
        assert any(a.id == sample_apoderado.alumnos[0].id for a in alumnos)

    def test_excludes_alumno_with_tag(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "aabbccdd"
        db_session.commit()
        alumnos = make_ctrl().get_alumnos_sin_tag()
        assert not any(a.id == alumno.id for a in alumnos)


# ---------------------------------------------------------------------------
# get_alumnos_activos
# ---------------------------------------------------------------------------

class TestGetAlumnosActivos:
    def test_returns_active_alumnos(self, db_session, sample_apoderado):
        alumnos = make_ctrl().get_alumnos_activos()
        assert any(a.id == sample_apoderado.alumnos[0].id for a in alumnos)

    def test_excludes_inactive_alumno(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.activo = False
        db_session.commit()
        alumnos = make_ctrl().get_alumnos_activos()
        assert not any(a.id == alumno.id for a in alumnos)


# ---------------------------------------------------------------------------
# get_alumno_by_tag
# ---------------------------------------------------------------------------

class TestGetAlumnoByTag:
    def test_returns_none_for_unknown_tag(self, db_session, sample_apoderado):
        result = make_ctrl().get_alumno_by_tag("FFFFFFFF")
        assert result is None

    def test_returns_alumno_for_known_tag(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "deadbeef"
        db_session.commit()
        result = make_ctrl().get_alumno_by_tag("deadbeef")
        assert result is not None
        assert result.id == alumno.id

    def test_tag_lookup_is_case_insensitive(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "abcd1234"
        db_session.commit()
        assert make_ctrl().get_alumno_by_tag("abcd1234") is not None
        assert make_ctrl().get_alumno_by_tag("ABCD1234") is not None


# ---------------------------------------------------------------------------
# get_alumno_con_orden
# ---------------------------------------------------------------------------

class TestGetAlumnoConOrden:
    def test_returns_not_found_for_unknown_tag(self, db_session, sample_apoderado):
        result = make_ctrl().get_alumno_con_orden("FFFFFFFF")
        assert result["alumno"] is None
        assert result["orden"] is None
        assert result["ya_entregado"] is False

    def test_returns_pending_orden(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "aa11bb22"
        db_session.commit()
        orden = _create_orden_casino(db_session, alumno, EstadoAlmuerzo.PENDIENTE)
        result = make_ctrl().get_alumno_con_orden("AA11BB22")
        assert result["alumno"].id == alumno.id
        assert result["orden"].id == orden.id
        assert result["ya_entregado"] is False

    def test_detects_ya_entregado(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "cc33dd44"
        db_session.commit()
        _create_orden_casino(db_session, alumno, EstadoAlmuerzo.ENTREGADO)
        result = make_ctrl().get_alumno_con_orden("CC33DD44")
        assert result["ya_entregado"] is True
        assert result["orden"] is None


# ---------------------------------------------------------------------------
# get_alumno_con_orden_by_id
# ---------------------------------------------------------------------------

class TestGetAlumnoConOrdenById:
    def test_returns_not_found_for_unknown_id(self, db_session, app):
        result = make_ctrl().get_alumno_con_orden_by_id(9999)
        assert result["alumno"] is None

    def test_returns_pending_orden(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        orden = _create_orden_casino(db_session, alumno, EstadoAlmuerzo.PENDIENTE)
        result = make_ctrl().get_alumno_con_orden_by_id(alumno.id)
        assert result["alumno"].id == alumno.id
        assert result["orden"].id == orden.id
        assert result["ya_entregado"] is False


# ---------------------------------------------------------------------------
# buscar_alumnos
# ---------------------------------------------------------------------------

class TestBuscarAlumnos:
    def test_returns_match_by_name(self, db_session, sample_apoderado):
        alumnos = make_ctrl().buscar_alumnos("Juan")
        assert any(a.id == sample_apoderado.alumnos[0].id for a in alumnos)

    def test_returns_empty_for_no_match(self, db_session, sample_apoderado):
        alumnos = make_ctrl().buscar_alumnos("ZZZNOMATCH")
        assert alumnos == []

    def test_is_case_insensitive(self, db_session, sample_apoderado):
        alumnos = make_ctrl().buscar_alumnos("juan")
        assert any(a.id == sample_apoderado.alumnos[0].id for a in alumnos)


# ---------------------------------------------------------------------------
# get_abono_by_codigo
# ---------------------------------------------------------------------------

class TestGetAbonoByCodigo:
    def test_returns_none_tuple_for_unknown_codigo(self, db_session, app):
        abono, pago, display_code = make_ctrl().get_abono_by_codigo("nonexistent-code")
        assert abono is None
        assert pago is None
        assert display_code == ""

    def test_returns_abono_when_found(self, db_session, sample_apoderado):
        from app.apoderado.controller import ApoderadoController
        created = ApoderadoController().create_abono(sample_apoderado, Decimal("5000"), "cafeteria")
        abono, pago, display_code = make_ctrl().get_abono_by_codigo(created.codigo)
        assert abono is not None
        assert abono.codigo == created.codigo
        assert pago is None
        assert display_code == ""


# ---------------------------------------------------------------------------
# get_pedido_with_payment
# ---------------------------------------------------------------------------

class TestGetPedidoWithPayment:
    def test_returns_none_for_unknown_codigo(self, db_session, app):
        pedido, pago = make_ctrl().get_pedido_with_payment("nonexistent-uuid")
        assert pedido is None
        assert pago is None

    def test_returns_pedido_without_payment(self, db_session, sample_apoderado):
        from app.apoderado.controller import ApoderadoController
        codigo = ApoderadoController().crea_orden(
            [{"slug": "menu-test", "date": "2026-03-01", "note": "", "alumnos": []}],
            apoderado_id=sample_apoderado.id,
        )
        pedido, pago = make_ctrl().get_pedido_with_payment(codigo)
        assert pedido is not None
        assert pedido.codigo == codigo
        assert pago is None


# ---------------------------------------------------------------------------
# entregar_almuerzo
# ---------------------------------------------------------------------------

class TestEntregarAlmuerzo:
    def test_marks_as_entregado(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        orden = _create_orden_casino(db_session, alumno, EstadoAlmuerzo.PENDIENTE)
        result = make_ctrl().entregar_almuerzo(orden.id)
        assert result is not None
        db_session.refresh(orden)
        assert orden.estado == EstadoAlmuerzo.ENTREGADO
        assert orden.fecha_entrega is not None

    def test_returns_none_for_already_entregado(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        orden = _create_orden_casino(db_session, alumno, EstadoAlmuerzo.ENTREGADO)
        result = make_ctrl().entregar_almuerzo(orden.id)
        assert result is None

    def test_returns_none_for_unknown_id(self, db_session, app):
        result = make_ctrl().entregar_almuerzo(99999)
        assert result is None


# ---------------------------------------------------------------------------
# crear_orden_kiosko
# ---------------------------------------------------------------------------

class TestCrearOrdenKiosko:
    def _make_menu(self, db_session):
        from app.model import MenuDiario
        menu = MenuDiario()
        menu.dia = date.today()
        menu.slug = f"menu-kiosko-{uuid.uuid4().hex[:8]}"
        menu.descripcion = "Menu Kiosko Test"
        menu.precio = Decimal("4400")
        menu.activo = True
        menu.fuera_stock = False
        menu.es_permanente = False
        db_session.add(menu)
        db_session.commit()
        return menu

    def test_creates_entregado_order(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        menu = self._make_menu(db_session)
        orden = make_ctrl().crear_orden_kiosko(alumno, menu)
        assert orden.id is not None
        assert orden.alumno_id == alumno.id
        assert orden.estado == EstadoAlmuerzo.ENTREGADO
        assert orden.fecha_entrega is not None
        assert orden.menu_slug == menu.slug


# ---------------------------------------------------------------------------
# approve_abono
# ---------------------------------------------------------------------------

class TestApproveAbono:
    def _create_abono_with_payment(self, db_session, apoderado, state="processing"):
        from app.apoderado.controller import ApoderadoController
        from app.model import Payment

        abono = ApoderadoController().create_abono(apoderado, Decimal("8000"), "cafeteria")
        pago = Payment()
        pago.session_id = abono.codigo
        pago.provider = "cafeteria"
        pago.state = state
        pago.amount = 8000
        pago.currency = "CLP"
        pago.redirect_url = "https://example.com/redirect"
        db_session.add(pago)
        db_session.commit()
        return abono, pago

    def test_approve_updates_state_and_saldo(self, db_session, sample_apoderado):
        abono, pago = self._create_abono_with_payment(db_session, sample_apoderado)
        initial_saldo = sample_apoderado.saldo_cuenta or 0
        result = make_ctrl().approve_abono(abono, pago)
        assert result is True
        db_session.refresh(pago)
        db_session.refresh(sample_apoderado)
        assert pago.state == "succeeded"
        assert sample_apoderado.saldo_cuenta == initial_saldo + 8000

    def test_returns_false_when_not_processing(self, db_session, sample_apoderado):
        abono, pago = self._create_abono_with_payment(db_session, sample_apoderado, state="succeeded")
        result = make_ctrl().approve_abono(abono, pago)
        assert result is False


# ---------------------------------------------------------------------------
# approve_pedido
# ---------------------------------------------------------------------------

class TestApprovePedido:
    def _create_pedido_with_payment(self, db_session, apoderado, state="processing"):
        from app.apoderado.controller import ApoderadoController
        from app.model import Payment, Pedido
        from app.database import db

        codigo_pedido = ApoderadoController().crea_orden(
            [{"slug": "menu-test", "date": "2026-03-01", "note": "", "alumnos": []}],
            apoderado_id=apoderado.id,
        )
        pedido = db_session.execute(db.select(Pedido).filter_by(codigo=codigo_pedido)).scalar_one()
        session_id = str(uuid.uuid4())
        pago = Payment()
        pago.session_id = session_id
        pago.provider = "cafeteria"
        pago.state = state
        pago.amount = 5000
        pago.currency = "CLP"
        pago.redirect_url = "https://example.com/redirect"
        db_session.add(pago)
        pedido.codigo_merchants = session_id
        db_session.commit()
        return pedido, pago

    def test_approve_sets_paid_state(self, db_session, sample_apoderado):
        from app.model import EstadoPedido
        pedido, pago = self._create_pedido_with_payment(db_session, sample_apoderado)
        result = make_ctrl().approve_pedido(pedido, pago)
        assert result is True
        db_session.refresh(pedido)
        db_session.refresh(pago)
        assert pago.state == "succeeded"
        assert pedido.pagado is True
        assert pedido.estado == EstadoPedido.PAGADO
        assert pedido.fecha_pago is not None

    def test_returns_false_when_not_processing(self, db_session, sample_apoderado):
        pedido, pago = self._create_pedido_with_payment(db_session, sample_apoderado, state="succeeded")
        result = make_ctrl().approve_pedido(pedido, pago)
        assert result is False
