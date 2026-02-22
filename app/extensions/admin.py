import os.path as op

from flask import flash, request, redirect, abort, url_for, current_app
from pathlib import Path
from flask_admin import Admin
from flask_admin.actions import action
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuDivider
from flask_admin.theme import Bootstrap4Theme
from slugify import slugify
from flask_security import current_user  # type: ignore
from .. import settings
from ..database import db
from ..model import Alumno, Apoderado, MenuDiario, OpcionMenuDia, Pedido, Plato, Role, Settings, User, Abono
from wtforms import SelectMultipleField
from flask_admin.form import Select2Widget
from wtforms import StringField
from wtforms.validators import Optional


admin = Admin(
    name="Sabor Mirandiano",
    url="/data-manager",
    theme=Bootstrap4Theme(fluid=True, swatch="united"),
)


class SecureModelView(ModelView):
    can_view_details = True

    def is_accessible(self):
        return current_user.is_active and current_user.is_authenticated and current_user.has_role("admin")

    def _handle_view(self, name, **kwargs):
        """
        Override builtin _handle_view in order to redirect users when a view is not
        accessible.
        """
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))


class UserView(SecureModelView):
    column_list = ["username", "email", "active", "roles"]


class FileView(FileAdmin):

    def is_accessible(self):
        return current_user.is_active and current_user.is_authenticated and current_user.has_role("admin")

    def _handle_view(self, name, **kwargs):
        """
        Override builtin _handle_view in order to redirect users when a view is not
        accessible.
        """
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))

    can_delete_dirs = False
    allowed_extensions = ("jpg", "jpeg", "png", "webp")
    upload_modal = False


class PlatoAdminView(SecureModelView):
    column_list = [
        "nombre",
        "activo",
        "es_vegano",
        "es_vegetariano",
        "es_hipocalorico",
        "contiene_gluten",
        "contiene_alergenos",
    ]


class MenuDiarioAdminView(SecureModelView):
    form_extra_fields = {
        "foto_principal": SelectMultipleField(label="Foto Principal", widget=Select2Widget(multiple=True))
    }
    column_list = [
        "dia",
        "slug",
        "es_permanente",
        "precio",
        "foto_principal",
    ]

    def _obtiene_fotos(self):
        base = Path(settings.DIRECTORIO_FOTOS_PLATO)
        return sorted(
            f.name for f in base.iterdir() if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )

    def edit_form(self, obj=None):
        form = super().edit_form(obj)
        form.foto_principal.choices = [(f, f) for f in self._obtiene_fotos()]  # type: ignore
        return form

    def create_form(self, obj=None):
        form = super().create_form(obj)
        form.foto_principal.choices = [(f, f) for f in self._obtiene_fotos()]  # type: ignore
        return form


class ApoderadoAdminView(SecureModelView):

    column_list = [
        "usuario",
        "nombre",
        "alumnos_registro",
        "maximo_diario",
        "maximo_semanal",
        "saldo_cuenta",
        "created",
    ]


class AlumnoAdminView(SecureModelView):

    column_list = [
        "apoderado",
        "nombre",
        "curso",
        "maximo_diario",
        "maximo_semanal",
        "tag",
        "created",
    ]

    form_overrides = {"tag": StringField}

    form_args = {
        "tag": {
            "validators": [Optional()],
            "render_kw": {
                "id": "tag-input",
                "readonly": True,
                "class": "form-control",
            },
        }
    }

    edit_template = "admin/alumno_edit.html"


class AbonoAdminView(SecureModelView):
    column_list = ["codigo", "apoderado", "monto", "forma_pago", "descripcion", "created"]

    @action(
        "enviar_comprobante",
        "Enviar Comprobante",
        "¿Enviar comprobante de pago a los apoderados seleccionados?",
    )
    def action_enviar_comprobante(self, ids):
        from ..tasks import send_comprobante_abono

        count = 0
        for abono_id in ids:
            abono = db.session.get(Abono, int(abono_id))
            if abono:
                send_comprobante_abono.delay(abono_id=abono.id)
                count += 1
        flash(f"Comprobante encolado para {count} abono(s).")


admin.add_view(PlatoAdminView(Plato, db.session, category="Casino"))
admin.add_view(
    FileView(
        settings.DIRECTORIO_FOTOS_PLATO,
        "/static/platos/",
        name="Administrador de Archivos",
        category="Casino",
    )
)
admin.add_view(MenuDiarioAdminView(MenuDiario, db.session, category="Casino"))
admin.add_view(SecureModelView(OpcionMenuDia, db.session, category="Casino", name="Items MenuDiario"))
admin.add_menu_item(MenuDivider(), target_category="Casino")
admin.add_view(SecureModelView(Pedido, db.session, category="Casino", name="Pedidos"))
admin.add_view(AbonoAdminView(Abono, db.session, category="Casino", name="Abonos"))

admin.add_view(UserView(User, db.session, category="Usuarios y Roles", name="Usuarios"))
admin.add_view(SecureModelView(Role, db.session, category="Usuarios y Roles", name="Roles"))
admin.add_menu_item(MenuDivider(), target_category="Usuarios y Roles")
admin.add_view(ApoderadoAdminView(Apoderado, db.session, category="Usuarios y Roles"))
admin.add_view(AlumnoAdminView(Alumno, db.session, category="Usuarios y Roles"))


admin.add_view(SecureModelView(Settings, db.session, name="Configuracion"))
