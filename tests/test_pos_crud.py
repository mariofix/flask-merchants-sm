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
# get_alumnos_con_almuerzo_pendiente
# ---------------------------------------------------------------------------

class TestGetAlumnosConAlmuerzoPendiente:
    def test_returns_alumno_with_pending_order(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        _create_orden_casino(db_session, alumno, EstadoAlmuerzo.PENDIENTE)
        alumnos = make_ctrl().get_alumnos_con_almuerzo_pendiente()
        assert any(a.id == alumno.id for a in alumnos)

    def test_excludes_alumno_with_entregado_order(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        _create_orden_casino(db_session, alumno, EstadoAlmuerzo.ENTREGADO)
        alumnos = make_ctrl().get_alumnos_con_almuerzo_pendiente()
        assert not any(a.id == alumno.id for a in alumnos)

    def test_excludes_alumno_without_order(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumnos = make_ctrl().get_alumnos_con_almuerzo_pendiente()
        assert not any(a.id == alumno.id for a in alumnos)

    def test_excludes_inactive_alumno(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        alumno.activo = False
        db_session.commit()
        _create_orden_casino(db_session, alumno, EstadoAlmuerzo.PENDIENTE)
        alumnos = make_ctrl().get_alumnos_con_almuerzo_pendiente()
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
# canjear_con_credito
# ---------------------------------------------------------------------------

class TestCanjearConCredito:
    def _make_menu(self, db_session, precio=Decimal("4000")):
        from app.model import MenuDiario
        menu = MenuDiario()
        menu.dia = date.today()
        menu.slug = f"menu-canje-{uuid.uuid4().hex[:8]}"
        menu.descripcion = "Menú Canje Test"
        menu.precio = precio
        menu.activo = True
        menu.fuera_stock = False
        menu.es_permanente = False
        db_session.add(menu)
        db_session.commit()
        return menu

    def test_creates_entregado_order_and_deducts_saldo(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        sample_apoderado.saldo_cuenta = 10000
        db_session.commit()
        alumno = sample_apoderado.alumnos[0]
        menu = self._make_menu(db_session)
        orden = make_ctrl().canjear_con_credito(alumno, menu)
        assert orden is not None
        assert orden.alumno_id == alumno.id
        assert orden.estado == EstadoAlmuerzo.ENTREGADO
        assert orden.fecha_entrega is not None
        assert orden.menu_slug == menu.slug
        db_session.refresh(sample_apoderado)
        assert sample_apoderado.saldo_cuenta == 6000

    def test_returns_none_when_insufficient_credit(self, db_session, sample_apoderado):
        sample_apoderado.saldo_cuenta = 100
        db_session.commit()
        alumno = sample_apoderado.alumnos[0]
        menu = self._make_menu(db_session, precio=Decimal("4000"))
        result = make_ctrl().canjear_con_credito(alumno, menu)
        assert result is None
        db_session.refresh(sample_apoderado)
        assert sample_apoderado.saldo_cuenta == 100  # unchanged

    def test_returns_none_when_zero_saldo(self, db_session, sample_apoderado):
        sample_apoderado.saldo_cuenta = 0
        db_session.commit()
        alumno = sample_apoderado.alumnos[0]
        menu = self._make_menu(db_session)
        result = make_ctrl().canjear_con_credito(alumno, menu)
        assert result is None

    def test_returns_none_when_menu_has_no_price(self, db_session, sample_apoderado):
        sample_apoderado.saldo_cuenta = 10000
        db_session.commit()
        alumno = sample_apoderado.alumnos[0]
        menu = self._make_menu(db_session, precio=None)
        result = make_ctrl().canjear_con_credito(alumno, menu)
        assert result is None

    def test_sets_apoderado_id_on_pedido(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo, Pedido
        from app.database import db as _db
        sample_apoderado.saldo_cuenta = 10000
        db_session.commit()
        alumno = sample_apoderado.alumnos[0]
        menu = self._make_menu(db_session)
        orden = make_ctrl().canjear_con_credito(alumno, menu)
        assert orden is not None
        pedido = db_session.execute(_db.select(Pedido).filter_by(codigo=orden.pedido_codigo)).scalar_one()
        assert pedido.apoderado_id == sample_apoderado.id


# ---------------------------------------------------------------------------
# get_dashboard_stats
# ---------------------------------------------------------------------------

class TestGetDashboardStats:
    def test_returns_zero_counts_when_no_data(self, db_session, app):
        stats = make_ctrl().get_dashboard_stats()
        assert stats["ordenes_pendientes_hoy"] == 0
        assert stats["ordenes_entregadas_hoy"] == 0
        assert stats["total_alumnos"] == 0
        assert stats["alumnos_con_tag"] == 0
        assert stats["porcentaje_cobertura_nfc"] == 0

    def test_counts_pending_and_delivered_orders(self, db_session, sample_apoderado):
        from app.model import EstadoAlmuerzo
        alumno = sample_apoderado.alumnos[0]
        _create_orden_casino(db_session, alumno, EstadoAlmuerzo.PENDIENTE)
        _create_orden_casino(db_session, alumno, EstadoAlmuerzo.ENTREGADO)
        stats = make_ctrl().get_dashboard_stats()
        assert stats["ordenes_pendientes_hoy"] == 1
        assert stats["ordenes_entregadas_hoy"] == 1

    def test_counts_alumnos_and_tag_coverage(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        # Alumno starts without a tag
        stats_before = make_ctrl().get_dashboard_stats()
        assert stats_before["total_alumnos"] >= 1
        assert stats_before["alumnos_con_tag"] == 0
        assert stats_before["porcentaje_cobertura_nfc"] == 0

        alumno.tag = "aabbccdd"
        db_session.commit()
        stats_after = make_ctrl().get_dashboard_stats()
        assert stats_after["alumnos_con_tag"] == 1
        assert stats_after["porcentaje_cobertura_nfc"] == 100

    def test_excludes_inactive_alumnos(self, db_session, sample_apoderado):
        alumno = sample_apoderado.alumnos[0]
        alumno.activo = False
        db_session.commit()
        stats = make_ctrl().get_dashboard_stats()
        assert stats["total_alumnos"] == 0

class TestApproveAbono:
    def _create_abono_with_payment(self, db_session, apoderado, state="processing"):
        from app.apoderado.controller import ApoderadoController
        from app.model import Payment

        abono = ApoderadoController().create_abono(apoderado, Decimal("8000"), "cafeteria")
        pago = Payment()
        pago.merchants_id = abono.codigo
        pago.transaction_id = abono.codigo
        pago.provider = "cafeteria"
        pago.state = state
        pago.amount = 8000
        pago.currency = "CLP"
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
        pago.merchants_id = session_id
        pago.transaction_id = session_id
        pago.provider = "cafeteria"
        pago.state = state
        pago.amount = 5000
        pago.currency = "CLP"
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


# ---------------------------------------------------------------------------
# crear_orden_admin
# ---------------------------------------------------------------------------

def _create_user1(db_session):
    """Create a User with id=1 for admin order tests."""
    import uuid
    from app.model import User
    from app.database import db

    # Check if id=1 already exists (other fixtures may have created it)
    existing = db_session.get(User, 1)
    if existing:
        return existing
    user = User()
    user.email = "admin@test.cl"
    user.username = "admin_user"
    user.password = "password"
    user.active = True
    user.fs_uniquifier = str(uuid.uuid4())
    db_session.add(user)
    db_session.flush()
    # Force id=1 by clearing and re-inserting if SQLite assigned a different id
    return db_session.get(User, 1) or user


class TestCrearOrdenAdmin:
    def _make_user1(self, db_session):
        import uuid
        from app.model import User
        user = User()
        user.email = "admin1@test.cl"
        user.username = "admin1_user"
        user.password = "password"
        user.active = True
        user.fs_uniquifier = str(uuid.uuid4())
        db_session.add(user)
        db_session.commit()
        return user

    def _make_menu(self, db_session):
        from datetime import date
        from app.model import MenuDiario
        menu = MenuDiario()
        menu.dia = date(2026, 6, 1)
        menu.slug = "menu-admin-test"
        menu.descripcion = "Menú de Prueba Admin"
        menu.precio = 3500
        menu.activo = True
        db_session.add(menu)
        db_session.commit()
        return menu

    def test_creates_orden_with_pedido_admin_codigo(self, db_session):
        from datetime import date
        from app.model import EstadoAlmuerzo
        user1 = self._make_user1(db_session)
        menu = self._make_menu(db_session)
        orden = make_ctrl().crear_orden_admin(
            nombre_alumno="Pedro Pérez",
            curso_alumno="3-A",
            fecha=date(2026, 6, 1),
            menu_slug=menu.slug,
        )
        assert orden is not None
        assert orden.pedido_codigo == "pedido-admin"
        assert orden.estado == EstadoAlmuerzo.PENDIENTE
        assert orden.menu_slug == menu.slug

    def test_creates_alumno_with_given_data(self, db_session):
        from datetime import date
        user1 = self._make_user1(db_session)
        menu = self._make_menu(db_session)
        orden = make_ctrl().crear_orden_admin(
            nombre_alumno="Ana López",
            curso_alumno="5-A",
            fecha=date(2026, 6, 1),
            menu_slug=menu.slug,
        )
        assert orden.alumno.nombre == "Ana López"
        assert orden.alumno.curso == "5-A"

    def test_stores_nota_from_contact_info(self, db_session):
        from datetime import date
        user1 = self._make_user1(db_session)
        menu = self._make_menu(db_session)
        orden = make_ctrl().crear_orden_admin(
            nombre_alumno="Carlos Ruiz",
            curso_alumno="2-B",
            fecha=date(2026, 6, 1),
            menu_slug=menu.slug,
            nota="correo: c@test.cl, tel: +56912345678",
        )
        assert "correo" in (orden.nota or "")
        assert "tel" in (orden.nota or "")

    def test_creates_apoderado_for_user1_if_missing(self, db_session):
        from datetime import date
        from app.model import Apoderado
        from app.database import db as _db
        user1 = self._make_user1(db_session)
        menu = self._make_menu(db_session)
        # Ensure no apoderado exists for user1
        existing = db_session.execute(
            _db.select(Apoderado).filter_by(usuario_id=user1.id)
        ).scalar_one_or_none()
        assert existing is None
        make_ctrl().crear_orden_admin(
            nombre_alumno="Test Alumno",
            curso_alumno="1-A",
            fecha=date(2026, 6, 1),
            menu_slug=menu.slug,
        )
        apoderado = db_session.execute(
            _db.select(Apoderado).filter_by(usuario_id=user1.id)
        ).scalar_one_or_none()
        assert apoderado is not None

    def test_raises_when_user1_missing(self, db_session):
        from datetime import date
        import pytest
        menu = self._make_menu(db_session)
        # No user1 in db for this test
        with pytest.raises(ValueError, match="Usuario 1"):
            make_ctrl().crear_orden_admin(
                nombre_alumno="No User",
                curso_alumno="1-A",
                fecha=date(2026, 6, 1),
                menu_slug=menu.slug,
            )
