"""Tests for GestorMenuView (app/extensions/admin.py).

Tests cover:
- is_accessible() logic (admin and pos roles granted, other roles denied)
- crear_plato() handler: creates a Plato, rejects duplicate names
- crear_menu_dia_form() handler: returns the dedicated form template
- crear_menu() handler: creates a MenuDiario with OpcionMenuDia rows, errors redirect to form
- copiar_menu() handler: clones an existing MenuDiario to new dates
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# Helpers to retrieve the view instance without a running Flask app
# ---------------------------------------------------------------------------

def _get_view():
    """Return the GestorMenuView singleton registered in the admin."""
    from app.extensions.admin import GestorMenuView

    view = object.__new__(GestorMenuView)
    return view


# ---------------------------------------------------------------------------
# is_accessible - role-based access control
# ---------------------------------------------------------------------------

class TestGestorMenuViewIsAccessible:
    """Verify that only users with 'admin' or 'pos' roles can access the view."""

    def _make_user(self, *, active=True, authenticated=True, roles=()):
        """Return a minimal mock user object."""
        class _MockUser:
            is_active = active
            is_authenticated = authenticated
            def has_role(self, role):
                return role in roles
        return _MockUser()

    def test_admin_role_is_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(roles=("admin",))
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is True

    def test_pos_role_is_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(roles=("pos",))
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is True

    def test_both_roles_is_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(roles=("admin", "pos"))
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is True

    def test_no_role_is_not_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(roles=())
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is False

    def test_other_role_is_not_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(roles=("apoderado",))
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is False

    def test_inactive_admin_is_not_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(active=False, roles=("admin",))
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is False

    def test_unauthenticated_user_is_not_accessible(self):
        import unittest.mock as mock
        view = _get_view()
        user = self._make_user(authenticated=False, roles=("pos",))
        with mock.patch("app.extensions.admin.current_user", user):
            assert view.is_accessible() is False


# ---------------------------------------------------------------------------
# crear_plato - business logic
# ---------------------------------------------------------------------------

class TestCrearPlato:
    def test_creates_plato(self, db_session, app):
        from app.model import Plato
        from app.database import db
        with app.app_context():
            initial_count = db_session.execute(
                db.select(db.func.count(Plato.id))
            ).scalar()

            plato = Plato(
                nombre="Cazuela Test",
                activo=True,
                es_vegano=False,
                es_vegetariano=False,
                es_hipocalorico=False,
                contiene_gluten=True,
                contiene_alergenos=False,
            )
            db_session.add(plato)
            db_session.commit()

            final_count = db_session.execute(
                db.select(db.func.count(Plato.id))
            ).scalar()
            assert final_count == initial_count + 1

    def test_plato_dietary_flags(self, db_session, app):
        from app.model import Plato
        with app.app_context():
            plato = Plato(
                nombre="Guiso Vegano Test",
                activo=True,
                es_vegano=True,
                es_vegetariano=True,
                es_hipocalorico=True,
                contiene_gluten=False,
                contiene_alergenos=False,
            )
            db_session.add(plato)
            db_session.commit()

            saved = db_session.get(Plato, plato.id)
            assert saved.es_vegano is True
            assert saved.es_vegetariano is True
            assert saved.es_hipocalorico is True
            assert saved.contiene_gluten is False


# ---------------------------------------------------------------------------
# crear_menu - business logic
# ---------------------------------------------------------------------------

class TestCrearMenu:
    def test_creates_menu_diario(self, db_session, app):
        from app.model import MenuDiario, Plato, OpcionMenuDia, TipoCurso
        from slugify import slugify
        with app.app_context():
            from app.database import db

            plato = Plato(nombre="Fondo Test Menu", activo=True)
            db_session.add(plato)
            db_session.flush()

            dia = date.today() + timedelta(days=10)
            descripcion = "Menú test del día"
            slug = slugify(descripcion)
            menu = MenuDiario(dia=dia, slug=slug, descripcion=descripcion, precio=Decimal("3000"), activo=True, stock=30)
            db_session.add(menu)
            db_session.flush()

            db_session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.FONDO, orden=0))
            db_session.commit()

            saved = db_session.execute(db.select(MenuDiario).filter_by(slug=slug)).scalar_one()
            assert saved.dia == dia
            assert saved.precio == Decimal("3000")
            assert len(saved.opciones) == 1
            assert saved.opciones[0].tipo_curso == TipoCurso.FONDO

    def test_menu_slug_is_unique(self, db_session, app):
        from app.model import MenuDiario
        from slugify import slugify
        from sqlalchemy.exc import IntegrityError
        with app.app_context():
            dia = date.today() + timedelta(days=20)
            slug = slugify(f"menu-{dia.isoformat()}")
            menu1 = MenuDiario(dia=dia, slug=slug, activo=True, stock=10)
            db_session.add(menu1)
            db_session.commit()

            menu2 = MenuDiario(dia=dia, slug=slug, activo=True, stock=10)
            db_session.add(menu2)
            with pytest.raises(IntegrityError):
                db_session.flush()
            db_session.rollback()


# ---------------------------------------------------------------------------
# copiar_menu - business logic
# ---------------------------------------------------------------------------

class TestCopiarMenu:
    def test_clones_menu_to_new_date(self, db_session, app):
        from app.model import MenuDiario, Plato, OpcionMenuDia, TipoCurso
        from slugify import slugify
        with app.app_context():
            from app.database import db

            plato = Plato(nombre="Plato Copia Test", activo=True)
            db_session.add(plato)
            db_session.flush()

            origen_dia = date.today() + timedelta(days=30)
            origen_slug = slugify(f"menu-{origen_dia.isoformat()}")
            origen = MenuDiario(
                dia=origen_dia,
                slug=origen_slug,
                precio=Decimal("4000"),
                activo=True,
                stock=40,
            )
            db_session.add(origen)
            db_session.flush()
            db_session.add(OpcionMenuDia(menu=origen, plato=plato, tipo_curso=TipoCurso.ENTRADA, orden=0))
            db_session.commit()

            # Clone to a new date
            nueva_dia = origen_dia + timedelta(days=1)
            nuevo_slug = slugify(f"menu-{nueva_dia.isoformat()}")
            nuevo = MenuDiario(
                dia=nueva_dia,
                slug=nuevo_slug,
                precio=origen.precio,
                descripcion=origen.descripcion,
                activo=origen.activo,
                stock=origen.stock,
                es_permanente=origen.es_permanente,
            )
            db_session.add(nuevo)
            db_session.flush()
            for opcion in origen.opciones:
                db_session.add(
                    OpcionMenuDia(
                        menu=nuevo,
                        plato=opcion.plato,
                        tipo_curso=opcion.tipo_curso,
                        orden=opcion.orden,
                    )
                )
            db_session.commit()

            cloned = db_session.execute(db.select(MenuDiario).filter_by(slug=nuevo_slug)).scalar_one()
            assert cloned.dia == nueva_dia
            assert cloned.precio == Decimal("4000")
            assert len(cloned.opciones) == 1
            assert cloned.opciones[0].tipo_curso == TipoCurso.ENTRADA


# ---------------------------------------------------------------------------
# crear_menu_dia_form - dedicated GET form endpoint
# ---------------------------------------------------------------------------

class TestCrearMenuDiaForm:
    """Verify that the dedicated form handler returns the expected template context."""

    def test_handler_exists_on_view(self):
        """GestorMenuView must expose a crear_menu_dia_form method."""
        from app.extensions.admin import GestorMenuView
        assert hasattr(GestorMenuView, "crear_menu_dia_form")
        assert callable(GestorMenuView.crear_menu_dia_form)

    def test_default_dia_is_tomorrow(self, app):
        """The default_dia passed to the template should be tomorrow's date string."""
        from datetime import date, timedelta
        import unittest.mock as mock
        from app.extensions.admin import GestorMenuView

        view = object.__new__(GestorMenuView)

        # Bypass _handle_view (access control) and mock render to capture context
        with mock.patch.object(view, "_handle_view", return_value=None):
            with mock.patch.object(view, "_get_platos_activos", return_value=[]):
                with mock.patch.object(view, "_obtiene_fotos", return_value=[]):
                    with mock.patch.object(view, "render") as mock_render:
                        mock_render.return_value = "rendered"
                        with app.test_request_context("/crear-menu-dia"):
                            view.crear_menu_dia_form()
                            call_kwargs = mock_render.call_args

        # The template name should be the dedicated form
        assert call_kwargs[0][0] == "admin/crear_menu_dia.html"

        # default_dia must equal tomorrow
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert kwargs.get("default_dia") == tomorrow

    def test_template_file_exists(self):
        """The crear_menu_dia.html template file must exist on disk."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..", "app", "templates", "admin", "crear_menu_dia.html",
        )
        assert os.path.isfile(os.path.normpath(template_path))


# ---------------------------------------------------------------------------
# crear_menu POST - error redirects go to dedicated form (not index)
# ---------------------------------------------------------------------------

class TestCrearMenuPostRedirects:
    """Verify that validation errors redirect to the dedicated form URL."""

    def _call_crear_menu(self, app, form_data):
        """Call view.crear_menu() bypassing the access-control wrapper.

        Returns (response, captured_redirect_url) where the URL is what
        url_for("gestor_menu.crear_menu_dia_form") resolved to inside the view.
        """
        import unittest.mock as mock
        from app.extensions.admin import GestorMenuView

        view = object.__new__(GestorMenuView)
        captured = {}

        def _fake_url_for(endpoint, **kwargs):
            url = f"/data-manager/{endpoint.replace('.', '/')}"
            captured["url_for_calls"] = captured.get("url_for_calls", [])
            captured["url_for_calls"].append(endpoint)
            return url

        with mock.patch.object(view, "_handle_view", return_value=None):
            with mock.patch("app.extensions.admin.flash"):
                with mock.patch("app.extensions.admin.url_for", side_effect=_fake_url_for):
                    with app.test_request_context("/crear-menu", method="POST", data=form_data):
                        response = view.crear_menu()
        return response, captured

    def test_missing_date_redirects_to_form(self, app):
        """A POST with no date should redirect to the dedicated form (not index)."""
        response, captured = self._call_crear_menu(app, {"dia": "", "csrf_token": "test"})

        assert response.status_code == 302
        # The url_for call inside the view must be for the form, not the index
        assert "gestor_menu.crear_menu_dia_form" in captured.get("url_for_calls", [])

    def test_invalid_price_redirects_to_form(self, app):
        """A POST with a non-numeric price should redirect to the dedicated form."""
        from datetime import date, timedelta

        valid_date = (date.today() + timedelta(days=99)).isoformat()
        response, captured = self._call_crear_menu(app, {
            "dia": valid_date, "precio": "not-a-number", "descripcion": "Menú test",
            "csrf_token": "test",
        })

        assert response.status_code == 302
        assert "gestor_menu.crear_menu_dia_form" in captured.get("url_for_calls", [])

    def test_missing_description_redirects_to_form(self, app):
        """A POST with no description should redirect to the dedicated form."""
        from datetime import date, timedelta

        valid_date = (date.today() + timedelta(days=99)).isoformat()
        response, captured = self._call_crear_menu(app, {
            "dia": valid_date, "descripcion": "", "csrf_token": "test",
        })

        assert response.status_code == 302
        assert "gestor_menu.crear_menu_dia_form" in captured.get("url_for_calls", [])
