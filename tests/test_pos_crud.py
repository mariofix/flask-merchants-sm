"""Tests for PosController (app/pos/crud.py).

Covers every public method using the shared fixtures from conftest.py.
Pure methods (no DB) are tested without fixtures; DB-dependent methods
use the session fixture.
"""

import uuid
from decimal import Decimal

import pytest

from app.pos.crud import PosController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctrl():
    return PosController()


# ---------------------------------------------------------------------------
# get_alumnos_sin_tag
# ---------------------------------------------------------------------------

class TestGetAlumnosSinTag:
    def test_returns_alumno_without_tag(self, db_session, sample_apoderado):
        # The alumno created in sample_apoderado has no tag by default
        alumnos = make_ctrl().get_alumnos_sin_tag()
        assert any(a.id == sample_apoderado.alumnos[0].id for a in alumnos)

    def test_excludes_alumno_with_tag(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "AABBCCDD"
        db_session.commit()
        alumnos = make_ctrl().get_alumnos_sin_tag()
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
        alumno.tag = "DEADBEEF"
        db_session.commit()
        result = make_ctrl().get_alumno_by_tag("deadbeef")  # test case-insensitive
        assert result is not None
        assert result.id == alumno.id

    def test_tag_lookup_is_case_insensitive(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.tag = "ABCD1234"
        db_session.commit()
        assert make_ctrl().get_alumno_by_tag("abcd1234") is not None
        assert make_ctrl().get_alumno_by_tag("ABCD1234") is not None


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
# approve_abono
# ---------------------------------------------------------------------------

class TestApproveAbono:
    def _create_abono_with_payment(self, db_session, apoderado, state="processing"):
        from app.apoderado.controller import ApoderadoController
        from app.model import Abono, Payment

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

        codigo_pedido = ApoderadoController().crea_orden(
            [{"slug": "menu-test", "date": "2026-03-01", "note": "", "alumnos": []}],
            apoderado_id=apoderado.id,
        )
        from app.database import db
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
