import os
import os.path as op

from flask import flash, request, redirect, abort, url_for, current_app
from pathlib import Path
from flask_admin import Admin, AdminIndexView, BaseView, expose
from flask_admin.actions import action
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuDivider, MenuLink
from flask_admin.theme import Bootstrap4Theme
from slugify import slugify
from flask_security import current_user  # type: ignore
from .. import settings
from ..database import db
from ..model import (
    Alumno,
    Apoderado,
    MenuDiario,
    OpcionMenuDia,
    Pedido,
    Plato,
    Role,
    Settings,
    User,
    Abono,
    OrdenCasino,
)
from wtforms import SelectMultipleField
from flask_admin.form import Select2Widget
from wtforms import StringField
from wtforms.validators import Optional


def _read_recent_audit_entries(n: int = 20) -> list[str]:
    """Return the last *n* lines from the merchants_audit log file.

    The log path is read from ``current_app.config['AUDIT_LOG_PATH']`` when
    available, falling back to ``logs/merchants_audit.log``.
    """
    from flask import current_app

    log_path = current_app.config.get("AUDIT_LOG_PATH", os.path.join("logs", "merchants_audit.log"))
    try:
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
        return [line.rstrip() for line in lines[-n:] if line.strip()]
    except OSError:
        return []


class SaborMirandianoIndexView(AdminIndexView):
    """Custom admin home page with summary stats and recent audit log entries."""

    @expose("/")
    def index(self):
        from ..model import Abono, Alumno, Pedido, Payment
        from datetime import date, timedelta

        if not (current_user.is_active and current_user.is_authenticated and current_user.has_role("admin")):
            return redirect(url_for("security.login", next=request.url))

        today = date.today()
        tomorrow = today + timedelta(days=1)

        pending_abonos = (
            db.session.execute(
                db.select(db.func.count(Abono.id))
                .join(Payment, Payment.session_id == Abono.codigo)
                .filter(Payment.state == "processing")
            ).scalar()
            or 0
        )

        active_alumnos = db.session.execute(db.select(db.func.count(Alumno.id))).scalar() or 0

        today_pedidos = (
            db.session.execute(
                db.select(db.func.count(Pedido.id)).filter(
                    Pedido.created >= today,
                    Pedido.created < tomorrow,
                )
            ).scalar()
            or 0
        )

        audit_entries = _read_recent_audit_entries()

        return self.render(
            "admin/index.html",
            pending_abonos=pending_abonos,
            active_alumnos=active_alumnos,
            today_pedidos=today_pedidos,
            audit_entries=audit_entries,
        )


admin = Admin(
    name="Sabor Mirandiano",
    url="/data-manager",
    theme=Bootstrap4Theme(fluid=True, swatch="united"),
    index_view=SaborMirandianoIndexView(url="/data-manager"),
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
        "aprobar_abono",
        "Aprobar Abono",
        "¿Aprobar los abonos seleccionados? Esto actualizará el saldo del apoderado.",
    )
    def action_aprobar_abono(self, ids):
        from ..tasks import send_comprobante_abono, send_notificacion_admin_abono, send_copia_notificaciones_abono
        from ..model import Payment
        from flask_merchants import merchants_audit

        count = 0
        for abono_id in ids:
            abono = db.session.get(Abono, int(abono_id))
            if not abono:
                continue
            pago = db.session.execute(db.select(Payment).filter_by(session_id=abono.codigo)).scalar_one_or_none()
            if not (pago and pago.state == "processing"):
                flash(f"Abono {abono.codigo[:8].upper()} no está pendiente de aprobación.", "warning")
                continue
            pago.state = "succeeded"
            saldo_actual = abono.apoderado.saldo_cuenta or 0
            nuevo_saldo = saldo_actual + int(abono.monto)
            abono.apoderado.saldo_cuenta = nuevo_saldo
            db.session.commit()
            merchants_audit.info(
                "abono_aprobado: codigo=%s apoderado_id=%s email=%r monto=%s nuevo_saldo=%s",
                abono.codigo,
                abono.apoderado.id,
                abono.apoderado.usuario.email,
                int(abono.monto),
                nuevo_saldo,
            )

            abono_info = {
                "id": abono.id,
                "codigo": abono.codigo,
                "monto": int(abono.monto),
                "forma_pago": abono.forma_pago,
                "descripcion": abono.descripcion,
                "apoderado_nombre": abono.apoderado.nombre,
                "apoderado_email": abono.apoderado.usuario.email,
                "saldo_anterior": saldo_actual,
                "saldo_cuenta": nuevo_saldo,
                "copia_notificaciones": abono.apoderado.copia_notificaciones,
            }
            # Admins are notified at code creation for cafeteria; only notify on approval for other providers.
            if abono.forma_pago != "cafeteria":
                send_notificacion_admin_abono.delay(abono_info=abono_info)
            if abono.apoderado.comprobantes_transferencia:
                send_comprobante_abono.delay(abono_info=abono_info)
                if abono.apoderado.copia_notificaciones:
                    send_copia_notificaciones_abono.delay(abono_info=abono_info)
            count += 1
        flash(f"{count} abono(s) aprobado(s) exitosamente.")

    @action(
        "enviar_comprobante",
        "Enviar Comprobante",
        "¿Enviar comprobante de pago a los apoderados seleccionados?",
    )
    def action_enviar_comprobante(self, ids):
        from ..tasks import send_comprobante_abono, send_notificacion_admin_abono, send_copia_notificaciones_abono

        count = 0
        for abono_id in ids:
            abono = db.session.get(Abono, int(abono_id))
            if abono:
                abono_info = {
                    "id": abono.id,
                    "codigo": abono.codigo,
                    "monto": int(abono.monto),
                    "forma_pago": abono.forma_pago,
                    "descripcion": abono.descripcion,
                    "apoderado_nombre": abono.apoderado.nombre,
                    "apoderado_email": abono.apoderado.usuario.email,
                    "saldo_cuenta": abono.apoderado.saldo_cuenta or 0,
                    "copia_notificaciones": abono.apoderado.copia_notificaciones,
                }
                send_comprobante_abono.delay(abono_info=abono_info)
                send_notificacion_admin_abono.delay(abono_info=abono_info)
                if abono.apoderado.comprobantes_transferencia and abono.apoderado.copia_notificaciones:
                    send_copia_notificaciones_abono.delay(abono_info=abono_info)
                count += 1
        flash(f"Comprobante encolado para {count} abono(s).")


class ResumenDiaAdminView(BaseView):
    """Vista de resumen de almuerzos comprados por día."""

    def is_accessible(self):
        return current_user.is_active and current_user.is_authenticated and current_user.has_role("admin")

    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        from datetime import date as _date

        from ..model import Alumno, EstadoAlmuerzo, OrdenCasino

        fecha_str = request.args.get("fecha", _date.today().isoformat())
        try:
            fecha = _date.fromisoformat(fecha_str)
        except ValueError:
            fecha = _date.today()
            fecha_str = fecha.isoformat()

        ordenes = (
            db.session.execute(
                db.select(OrdenCasino)
                .where(OrdenCasino.fecha == fecha)
                .order_by(OrdenCasino.menu_slug, OrdenCasino.alumno_id)
            )
            .scalars()
            .all()
        )

        # Pre-load all alumnos in one query to avoid N+1
        alumno_ids = list({o.alumno_id for o in ordenes if o.alumno_id})
        alumnos_by_id: dict = {}
        if alumno_ids:
            alumnos_by_id = {
                a.id: a
                for a in db.session.execute(
                    db.select(Alumno).where(Alumno.id.in_(alumno_ids))
                )
                .scalars()
                .all()
            }

        def _iniciales(nombre: str | None) -> str:
            if not nombre:
                return "—"
            return "".join(p[0].upper() + "." for p in nombre.strip().split() if p)

        menus: dict = {}
        total_monto = 0
        for orden in ordenes:
            slug = orden.menu_slug
            desc = orden.menu_descripcion or slug
            if slug not in menus:
                menus[slug] = {
                    "descripcion": desc, "total": 0, "monto": 0,
                    "pendientes": 0, "entregados": 0, "cancelados": 0,
                }
            menus[slug]["total"] += 1
            precio = int(orden.menu_precio) if orden.menu_precio else 0
            menus[slug]["monto"] += precio
            total_monto += precio
            if orden.estado == EstadoAlmuerzo.PENDIENTE:
                menus[slug]["pendientes"] += 1
            elif orden.estado == EstadoAlmuerzo.ENTREGADO:
                menus[slug]["entregados"] += 1
            elif orden.estado == EstadoAlmuerzo.CANCELADO:
                menus[slug]["cancelados"] += 1

        detalles = []
        for orden in ordenes:
            alumno = alumnos_by_id.get(orden.alumno_id)
            detalles.append({
                "orden_id": orden.id,
                "iniciales": _iniciales(alumno.nombre if alumno else None),
                "curso": alumno.curso if alumno else "—",
                "menu": orden.menu_descripcion or orden.menu_slug,
                "precio": int(orden.menu_precio) if orden.menu_precio else 0,
                "estado": orden.estado.value,
                "nota": orden.nota or "",
            })

        return self.render(
            "admin/resumen_dia.html",
            fecha=fecha,
            fecha_str=fecha_str,
            ordenes_total=len(ordenes),
            total_monto=total_monto,
            menus=menus,
            detalles=detalles,
        )


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
admin.add_view(SecureModelView(OrdenCasino, db.session, category="Casino", name="Ordenes"))
admin.add_view(ResumenDiaAdminView(name="Resumen del Día", endpoint="resumen_dia", category="Casino"))


admin.add_view(UserView(User, db.session, category="Usuarios y Roles", name="Usuarios"))
admin.add_view(SecureModelView(Role, db.session, category="Usuarios y Roles", name="Roles"))
admin.add_menu_item(MenuDivider(), target_category="Usuarios y Roles")
admin.add_view(ApoderadoAdminView(Apoderado, db.session, category="Usuarios y Roles"))
admin.add_view(AlumnoAdminView(Alumno, db.session, category="Usuarios y Roles"))


admin.add_view(SecureModelView(Settings, db.session, name="Configuracion"))

admin.add_link(MenuLink(name="Sitio Web", endpoint="core.index", icon_type="glyph", icon_value="glyphicon-home"))
admin.add_link(MenuLink(name="POS", endpoint="pos.index", icon_type="glyph", icon_value="glyphicon-shopping-cart"))
admin.add_link(MenuLink(name="Apoderado", endpoint="apoderado_cliente.index", icon_type="glyph", icon_value="glyphicon-user"))
admin.add_link(MenuLink(name="Mi Cuenta", endpoint="security.change_password", icon_type="glyph", icon_value="glyphicon-cog"))
admin.add_link(MenuLink(name="Cerrar Sesión", endpoint="security.logout", icon_type="glyph", icon_value="glyphicon-log-out"))
