import os
import os.path as op

from flask import flash, request, redirect, abort, url_for, current_app
from pathlib import Path
from flask_admin import Admin, AdminIndexView, BaseView, expose
from flask_admin.actions import action
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.contrib.rediscli import RedisCli
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuDivider, MenuLink
from flask_admin.theme import Bootstrap4Theme
from slugify import slugify
from flask_security import current_user  # type: ignore
from . import csrf
from .. import settings
from ..database import db
from ..model import (
    Alumno,
    Apoderado,
    MenuDiario,
    OpcionMenuDia,
    Payment,
    Pedido,
    Plato,
    Role,
    Settings,
    TipoCurso,
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


class SecureRedisCli(RedisCli):
    """Redis CLI console restricted to admin users."""

    def is_accessible(self):
        return current_user.is_active and current_user.is_authenticated and current_user.has_role("admin")

    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))

    @expose("/run/", methods=("POST",))
    @csrf.exempt
    def execute_view(self):
        return super().execute_view()


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

    @action(
        "vaciar_tabla",
        "Vaciar Tabla",
        "⚠️ Esto eliminará TODOS los platos y sus asignaciones en menús. ¿Continuar?",
    )
    def action_vaciar_tabla(self, ids):
        try:
            db.session.execute(db.delete(OpcionMenuDia))
            count = db.session.execute(db.delete(Plato)).rowcount
            db.session.commit()
            flash(f"Se eliminaron {count} plato(s) y todas las asignaciones de menú asociadas.")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error al vaciar tabla: {exc}", "error")


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

    form_widget_args = {
        "slug": {
            "readonly": True,
        }
    }

    create_template = "admin/menudiario_form.html"
    edit_template = "admin/menudiario_edit.html"

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

    @action(
        "vaciar_tabla",
        "Vaciar Tabla",
        "⚠️ Esto eliminará TODOS los menús diarios y sus opciones. ¿Continuar?",
    )
    def action_vaciar_tabla(self, ids):
        try:
            count = db.session.execute(db.delete(MenuDiario)).rowcount
            db.session.commit()
            flash(f"Se eliminaron {count} menú(s) diario(s) y todas sus opciones.")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error al vaciar tabla: {exc}", "error")


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

    @action(
        "vaciar_tabla",
        "Vaciar Tabla",
        "⚠️ Esto eliminará TODOS los apoderados, sus alumnos y abonos. ¿Continuar?",
    )
    def action_vaciar_tabla(self, ids):
        try:
            db.session.execute(db.delete(OrdenCasino))
            db.session.execute(db.delete(Alumno))
            db.session.execute(db.delete(Payment))
            db.session.execute(db.delete(Abono))
            count = db.session.execute(db.delete(Apoderado)).rowcount
            db.session.commit()
            flash(f"Se eliminaron {count} apoderado(s) y todos sus alumnos, abonos y pagos.")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error al vaciar tabla: {exc}", "error")


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

    @action(
        "vaciar_tabla",
        "Vaciar Tabla",
        "⚠️ Esto eliminará TODOS los alumnos y sus órdenes de casino. ¿Continuar?",
    )
    def action_vaciar_tabla(self, ids):
        try:
            db.session.execute(db.delete(OrdenCasino))
            count = db.session.execute(db.delete(Alumno)).rowcount
            db.session.commit()
            flash(f"Se eliminaron {count} alumno(s) y todas sus órdenes de casino.")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error al vaciar tabla: {exc}", "error")


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




# ---------------------------------------------------------------------------
# Generador de Datos de Prueba
# ---------------------------------------------------------------------------

# Platos chilenos organizados por categoría con flags dietéticos consistentes
# Formato: (nombre, es_vegano, es_vegetariano, es_hipocalorico, contiene_gluten, contiene_alergenos)
_PLATOS_FONDOS_CARNE = [
    ("Cazuela de Vacuno", False, False, False, False, False),
    ("Cazuela de Pollo", False, False, False, False, False),
    ("Pollo Asado con Papas", False, False, False, False, False),
    ("Filete de Merluza al Vapor", False, False, True, False, True),
    ("Bistec a lo Pobre", False, False, False, False, False),
    ("Charquicán", False, False, False, False, False),
    ("Pastel de Choclo", False, False, False, False, False),
    ("Arrollado de Huaso", False, False, False, False, False),
    ("Guiso de Lentejas con Costilla", False, False, False, False, False),
    ("Carne Mechada con Arroz", False, False, False, False, False),
    ("Pollo a la Plancha con Ensalada", False, False, True, False, False),
    ("Reineta al Horno", False, False, True, False, True),
    ("Salmón a la Plancha", False, False, True, False, True),
    ("Ajiaco", False, False, False, False, False),
    ("Guiso de Porotos con Longaniza", False, False, False, False, False),
    # --- tramo 2 ---
    ("Pollo al Horno con Arroz", False, False, False, False, False),
    ("Trutro de Pollo Asado", False, False, False, False, False),
    ("Milanesa de Pollo con Puré", False, False, False, True, False),
    ("Milanesa de Vacuno", False, False, False, True, False),
    ("Pollo Arvejado", False, False, False, False, False),
    ("Tallarines con Carne Molida", False, False, False, True, False),
    ("Churrasco con Palta", False, False, False, False, False),
    ("Costillas de Cerdo al Horno", False, False, False, False, False),
    ("Lomo Saltado", False, False, False, False, False),
    ("Pollo con Champiñones", False, False, False, False, False),
    ("Albóndigas al Jugo con Arroz", False, False, False, False, False),
    ("Pollo Relleno al Horno", False, False, False, False, False),
    ("Pechuga de Pollo a la Plancha", False, False, True, False, False),
    ("Filete de Cerdo con Papas Doradas", False, False, False, False, False),
    ("Atún al Horno con Verduras", False, False, True, False, True),
    # --- tramo 3 ---
    ("Salmón en Salsa de Limón", False, False, True, False, True),
    ("Ropa Vieja", False, False, False, False, False),
    ("Carbonada", False, False, False, False, False),
    ("Pollo Saltado con Verduras", False, False, True, False, False),
    ("Asado de Tira con Ensalada", False, False, False, False, False),
    ("Caldillo de Congrio", False, False, False, False, True),
    ("Pollo Escabechado", False, False, False, False, False),
    ("Vacuno Estofado con Papas", False, False, False, False, False),
    ("Carne al Jugo con Puré", False, False, False, False, False),
    ("Pollo con Salsa de Tomate", False, False, False, False, False),
    ("Guiso de Vacuno con Papas", False, False, False, False, False),
    ("Pescado Frito con Ensalada", False, False, False, True, True),
    ("Carne con Arroz y Ensalada", False, False, False, False, False),
    ("Guiso de Mariscos", False, False, False, False, True),
    ("Pollo a la Cerveza", False, False, False, False, False),
]

_PLATOS_FONDOS_VEGANOS = [
    ("Guiso de Lentejas Vegano", True, True, True, False, False),
    ("Estofado de Garbanzos", True, True, True, False, False),
    ("Arroz con Verduras Salteadas", True, True, True, False, False),
    ("Pastel de Papas Vegano", True, True, False, False, False),
    ("Puré de Zapallo con Quinoa", True, True, True, False, False),
    ("Cazuela de Verduras", True, True, True, False, False),
    ("Porotos con Rienda Vegano", True, True, False, False, False),
    ("Tarta de Espinacas", True, True, False, True, False),
    # --- tramo 2 ---
    ("Burger de Lentejas", True, True, False, True, False),
    ("Curry de Garbanzos con Arroz", True, True, True, False, False),
    ("Estofado de Zapallo y Papas", True, True, True, False, False),
    ("Lasaña Vegana de Espinacas", True, True, False, True, False),
    ("Sopa de Quinoa con Verduras", True, True, True, False, False),
    ("Burger de Porotos Negros", True, True, False, True, False),
    ("Risotto de Champiñones Vegano", True, True, False, False, False),
    ("Cazuela de Porotos Negros", True, True, True, False, False),
    # --- tramo 3 ---
    ("Guiso de Lentejas con Espinaca", True, True, True, False, False),
    ("Sopa de Tomate y Albahaca", True, True, True, False, False),
    ("Guiso de Quinoa con Tomate", True, True, True, False, False),
    ("Arroz Salteado con Brócoli Vegano", True, True, True, False, False),
    ("Wrap de Verduras Asadas", True, True, True, True, False),
    ("Stir-Fry de Verduras con Fideos", True, True, False, True, False),
    ("Tacos de Champiñones Vegano", True, True, False, True, False),
    ("Crema de Lentejas Rojas", True, True, True, False, False),
]

_PLATOS_FONDOS_VEGETARIANOS = [
    ("Tortilla de Acelga", False, True, True, False, True),
    ("Lasaña de Verduras", False, True, False, True, True),
    ("Revuelto Gramajo", False, True, False, False, True),
    ("Omelette con Queso y Tomate", False, True, True, False, True),
    ("Quiche de Espinacas", False, True, False, True, True),
    ("Fideos con Salsa de Tomate", False, True, False, True, False),
    ("Arroz con Leche de Coco", False, True, True, False, False),
    # --- tramo 2 ---
    ("Pasta con Salsa de Champiñones", False, True, False, True, False),
    ("Frittata de Verduras", False, True, True, False, True),
    ("Soufflé de Queso", False, True, False, False, True),
    ("Risotto de Parmesano", False, True, False, False, True),
    ("Crepes Vegetarianos Rellenos", False, True, False, True, True),
    ("Tarta de Tomate y Queso", False, True, False, True, True),
    ("Gnocchi de Espinaca con Mantequilla", False, True, False, True, True),
    # --- tramo 3 ---
    ("Revuelto de Verduras con Queso", False, True, True, False, True),
    ("Pasta Primavera", False, True, False, True, False),
    ("Quesadillas de Espinaca", False, True, True, True, True),
    ("Budín de Zapallo", False, True, True, False, True),
    ("Pizza de Verduras", False, True, False, True, True),
    ("Strúdel de Queso y Espinaca", False, True, False, True, True),
    ("Tortilla Española de Papas", False, True, False, False, True),
]

_PLATOS_ENTRADAS = [
    ("Sopa de Cebolla", True, True, False, False, False),
    ("Crema de Zapallo", True, True, True, False, False),
    ("Consomé de Pollo", False, False, True, False, False),
    ("Sopa Minestrone", True, True, False, False, False),
    ("Ensalada Chilena", True, True, True, False, False),
    ("Ensalada César", False, False, False, False, True),
    ("Ensalada de Tomate y Cebolla", True, True, True, False, False),
    ("Empanadas de Horno", False, False, False, True, False),
    ("Humitas", True, True, False, False, False),
    ("Pebre con Marraqueta", True, True, False, True, False),
    # --- tramo 2 ---
    ("Sopa de Zapallo Camote", True, True, True, False, False),
    ("Crema de Zanahoria", True, True, True, False, False),
    ("Sopa de Tomate Casera", True, True, True, False, False),
    ("Ensalada de Remolacha", True, True, True, False, False),
    ("Ensalada de Repollo y Zanahoria", True, True, True, False, False),
    ("Sopa de Verduras del Día", True, True, True, False, False),
    ("Tomaticán", True, True, True, False, False),
    ("Porotos Granados", True, True, False, False, False),
    ("Sopa de Choclo", True, True, False, False, False),
    ("Sopa de Papas con Cilantro", True, True, True, False, False),
    # --- tramo 3 ---
    ("Pan Amasado con Pebre", True, True, False, True, False),
    ("Tostadas con Tomate y Ajo", True, True, False, True, False),
    ("Crema de Brócoli", False, True, True, False, True),
    ("Ensalada de Pollo y Lechuga", False, False, True, False, False),
    ("Ceviche de Mariscos", False, False, True, False, True),
    ("Guacamole con Tostadas", True, True, True, True, False),
    ("Sopa de Cebolla Gratinada", False, True, False, True, True),
    ("Crema de Espárragos", False, True, True, False, True),
    ("Ensalada Griega", False, True, True, False, True),
    ("Ensalada de Pepino con Yogurt", False, True, True, False, True),
]

_PLATOS_POSTRES = [
    ("Arroz con Leche", False, True, False, False, True),
    ("Leche Asada", False, True, False, False, True),
    ("Kuchen de Frutas", False, True, False, True, True),
    ("Mote con Huesillos", True, True, True, False, False),
    ("Sopaipillas con Chancaca", True, True, False, True, False),
    ("Gelatina de Frutas", True, True, True, False, False),
    ("Flan de Vainilla", False, True, False, False, True),
    ("Picarones", True, True, False, True, False),
    ("Fruta de Temporada", True, True, True, False, False),
    ("Torta de Milhojas", False, True, False, True, True),
    # --- tramo 2 ---
    ("Mousse de Maracuyá", False, True, True, False, True),
    ("Alfajores", False, True, False, True, True),
    ("Queque de Naranja", False, True, False, True, True),
    ("Budín de Pan", False, True, False, True, True),
    ("Merengue con Crema", False, True, False, False, True),
    ("Copa de Helado de Frutilla", False, True, False, False, True),
    ("Ensalada de Frutas Frescas", True, True, True, False, False),
    ("Panqueques con Manjar", False, True, False, True, True),
    ("Queque de Chocolate", False, True, False, True, True),
    ("Mazamorra de Maíz", True, True, True, False, False),
    # --- tramo 3 ---
    ("Manzana al Horno", True, True, True, False, False),
    ("Plátano con Miel", True, True, True, False, False),
    ("Gelatina de Frambuesa", True, True, True, False, False),
    ("Suspiro Limeño", False, True, False, False, True),
    ("Chilenitos", False, True, False, True, True),
    ("Copa de Frutas Naturales", True, True, True, False, False),
    ("Turrón de Merengue", False, True, False, False, True),
    ("Kuchen de Manzana", False, True, False, True, True),
    ("Yogurt con Granola y Frutas", False, True, True, True, True),
    ("Manjar Casero con Galleta", False, True, False, True, True),
]

_CURSOS_FALLBACK = [
    "1° Básico A", "1° Básico B", "2° Básico A", "2° Básico B",
    "3° Básico A", "3° Básico B", "4° Básico A", "4° Básico B",
    "5° Básico A", "5° Básico B", "6° Básico A", "6° Básico B",
    "7° Básico A", "7° Básico B", "8° Básico A", "8° Básico B",
    "1° Medio A", "1° Medio B", "2° Medio A", "2° Medio B",
    "3° Medio A", "3° Medio B", "4° Medio A", "4° Medio B",
]


def _get_cursos() -> list[str]:
    """Return the list of school courses from Settings(slug='cursos').

    ``Settings.value`` is a SQLAlchemy JSON column, so it is already
    deserialized to a Python object when read.  The expected shape is a list
    of strings, e.g. ``["1-A", "1-B", "2-A", ...]``.  Falls back to
    ``_CURSOS_FALLBACK`` when the setting is absent, inactive, or empty.
    """
    setting = db.session.execute(
        db.select(Settings).filter_by(slug="cursos", active=True)
    ).scalar_one_or_none()
    if setting and isinstance(setting.value, list) and setting.value:
        return [str(c) for c in setting.value]
    return _CURSOS_FALLBACK


def _hora_escolar_aleatoria(fecha, tipo: str = "general"):
    """Return a datetime for *fecha* at a context-appropriate time.

    tipos:
    - ``"pedido"``     – parents place orders before the kitchen cutoff (07:30-11:30)
    - ``"abono"``      – a parent initiates a payment; this can happen at any hour,
                         including late at night via Khipu (00:00-23:59)
    - ``"validacion"`` – an admin validates/approves a payment; only during office
                         hours on weekdays (08:00-18:00, Mon-Fri)
    - ``"entrega"``    – lunch is served during the lunch break (12:00-13:30)
    - ``"general"``    – generic school-hours activity (08:00-17:00)
    """
    import random
    from datetime import datetime, timedelta

    if tipo == "pedido":
        hora = random.randint(7, 11)
        minuto = random.randint(30 if hora == 7 else 0, 59 if hora < 11 else 30)
    elif tipo == "abono":
        # Parents can pay at 2 AM via Khipu — no time restriction
        hora = random.randint(0, 23)
        minuto = random.randint(0, 59)
    elif tipo == "validacion":
        # Admins only work Mon-Fri 08:00-18:00; advance to Monday if on a weekend
        fecha_val = fecha
        while fecha_val.weekday() >= 5:
            fecha_val += timedelta(days=1)
        hora = random.randint(8, 17)
        minuto = random.randint(0, 59)
        return datetime(fecha_val.year, fecha_val.month, fecha_val.day, hora, minuto, random.randint(0, 59))
    elif tipo == "entrega":
        hora = random.choices([12, 13], weights=[7, 3])[0]
        minuto = random.randint(0, 59 if hora == 12 else 30)
    else:
        hora = random.randint(8, 17)
        minuto = random.randint(0, 59)

    return datetime(fecha.year, fecha.month, fecha.day, hora, minuto, random.randint(0, 59))


_RESTRICCIONES_CATALOGO = [
    {"nombre": "Maní", "motivo": "Alergia"},
    {"nombre": "Mariscos", "motivo": "Alergia"},
    {"nombre": "Huevo", "motivo": "Alergia"},
    {"nombre": "Soya", "motivo": "Alergia"},
    {"nombre": "Palta", "motivo": "Intolerancia"},
    {"nombre": "Lactosa", "motivo": "Intolerancia"},
    {"nombre": "Gluten", "motivo": "Intolerancia"},
    {"nombre": "Uva", "motivo": "Intolerancia"},
    {"nombre": "Vegano", "motivo": "Preferencia"},
    {"nombre": "Vegetariano", "motivo": "Preferencia"},
]


def _restricciones_aleatorias(rng) -> list:
    """Return a random (possibly empty) list of restricciones dicts."""
    if rng.random() > 0.30:
        return []
    return rng.sample(_RESTRICCIONES_CATALOGO, k=rng.randint(1, 2))


class GenerarDatosView(BaseView):
    """Vista de administración para generar datos de prueba contextualizados."""

    def is_accessible(self):
        return current_user.is_active and current_user.is_authenticated and current_user.has_role("admin")

    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))

    def _get_conteos(self) -> dict:
        from ..model import Abono, Alumno, Apoderado, MenuDiario, OpcionMenuDia, OrdenCasino, Payment, Pedido, Plato, Settings, User, Role

        return {
            "Platos": db.session.execute(db.select(db.func.count(Plato.id))).scalar() or 0,
            "Menús Diarios": db.session.execute(db.select(db.func.count(MenuDiario.id))).scalar() or 0,
            "Apoderados": db.session.execute(db.select(db.func.count(Apoderado.id))).scalar() or 0,
            "Alumnos": db.session.execute(db.select(db.func.count(Alumno.id))).scalar() or 0,
            "Abonos": db.session.execute(db.select(db.func.count(Abono.id))).scalar() or 0,
            "Pedidos": db.session.execute(db.select(db.func.count(Pedido.id))).scalar() or 0,
            "Ordenes Casino": db.session.execute(db.select(db.func.count(OrdenCasino.id))).scalar() or 0,
            "Pagos": db.session.execute(db.select(db.func.count(Payment.id))).scalar() or 0,
            "Configuraciones": db.session.execute(db.select(db.func.count(Settings.id))).scalar() or 0,
            "Usuarios": db.session.execute(db.select(db.func.count(User.id))).scalar() or 0,
            "Roles": db.session.execute(db.select(db.func.count(Role.id))).scalar() or 0,
        }

    @expose("/")
    def index(self):
        return self.render("admin/generar_datos.html", conteos=self._get_conteos())

    @expose("/generar", methods=["POST"])
    def generar(self):
        import random
        from datetime import date, timedelta

        from faker import Faker

        fake = Faker("es_CL")

        modelo = request.form.get("modelo", "plato")
        try:
            cantidad = min(int(request.form.get("cantidad", 10)), 100)
        except (ValueError, TypeError):
            cantidad = 10

        creados = 0

        if modelo == "plato":
            creados = self._generar_platos(fake, cantidad)
        elif modelo == "alumno":
            creados = self._generar_alumnos(fake, cantidad)
        elif modelo == "apoderado":
            creados = self._generar_apoderados(fake, cantidad)
        elif modelo == "menu_diario":
            creados = self._generar_menus_diarios(fake, cantidad)
        else:
            flash(f"Modelo desconocido: {modelo}", "error")
            return redirect(url_for("generar_datos.index"))

        nombres = {
            "plato": "Plato(s)",
            "alumno": "Alumno(s)",
            "apoderado": "Apoderado(s) completo(s) (Usuario + Alumnos + Abonos)",
            "menu_diario": "Menú(s) Diario(s)",
        }
        flash(f"✅ Se crearon {creados} {nombres.get(modelo, modelo)} exitosamente.", "success")
        return redirect(url_for("generar_datos.index"))

    def _generar_platos(self, fake, cantidad: int) -> int:
        import random

        todos = _PLATOS_ENTRADAS + _PLATOS_FONDOS_CARNE + _PLATOS_FONDOS_VEGANOS + _PLATOS_FONDOS_VEGETARIANOS + _PLATOS_POSTRES
        creados = 0
        usados = set(
            row[0]
            for row in db.session.execute(db.select(Plato.nombre)).all()
        )

        candidatos = [p for p in todos if p[0] not in usados]
        random.shuffle(candidatos)

        for i in range(min(cantidad, len(candidatos))):
            nombre, vegano, vegetariano, hipocalorico, gluten, alergenos = candidatos[i]
            plato = Plato(
                nombre=nombre,
                activo=True,
                es_vegano=vegano,
                es_vegetariano=vegetariano,
                es_hipocalorico=hipocalorico,
                contiene_gluten=gluten,
                contiene_alergenos=alergenos,
            )
            db.session.add(plato)
            creados += 1

        if creados < cantidad:
            # If we've run out of predefined names, generate unique ones
            for _ in range(cantidad - creados):
                categoria = random.choice(["entrada", "fondo", "postre"])
                if categoria == "fondo":
                    base = random.choice(["Guiso", "Cazuela", "Estofado", "Asado", "Salteado"])
                    ingrediente = fake.word().capitalize()
                    nombre = f"{base} de {ingrediente}"
                    vegano = random.random() < 0.3
                    vegetariano = vegano or (random.random() < 0.2)
                elif categoria == "entrada":
                    base = random.choice(["Sopa", "Crema", "Ensalada", "Consomé"])
                    ingrediente = fake.word().capitalize()
                    nombre = f"{base} de {ingrediente}"
                    vegano = random.random() < 0.5
                    vegetariano = vegano or (random.random() < 0.3)
                else:
                    nombre = fake.word().capitalize() + " dulce"
                    vegano = random.random() < 0.4
                    vegetariano = vegano or (random.random() < 0.4)

                plato = Plato(
                    nombre=nombre,
                    activo=True,
                    es_vegano=vegano,
                    es_vegetariano=vegetariano,
                    es_hipocalorico=random.random() < 0.3,
                    contiene_gluten=random.random() < 0.4,
                    contiene_alergenos=random.random() < 0.2,
                )
                db.session.add(plato)
                creados += 1

        db.session.commit()
        return creados

    def _generar_alumnos(self, fake, cantidad: int) -> int:
        import random

        apoderados = db.session.execute(db.select(Apoderado)).scalars().all()
        if not apoderados:
            flash("No hay Apoderados disponibles. Crea Apoderados primero.", "error")
            return 0

        creados = 0
        cursos = _get_cursos()
        for _ in range(cantidad):
            nombre = f"{fake.first_name()} {fake.last_name()}"
            curso = random.choice(cursos)
            slug_base = f"{nombre.lower().replace(' ', '-')}-{random.randint(1, 999)}"
            from slugify import slugify as _slugify
            slug = _slugify(slug_base)

            alumno = Alumno(
                slug=slug,
                nombre=nombre,
                curso=curso,
                activo=True,
                apoderado=random.choice(apoderados),
                maximo_diario=random.choice([None, 1, 2, 3]),
                maximo_semanal=random.choice([None, 5, 10]),
                restricciones=_restricciones_aleatorias(random),
            )
            db.session.add(alumno)
            creados += 1

        db.session.commit()
        return creados

    def _generar_apoderados(self, fake, cantidad: int) -> int:
        import random
        import uuid
        from datetime import date, timedelta
        from decimal import Decimal

        from flask_security.utils import hash_password
        from slugify import slugify as _slugify

        # Get or create a plain "apoderado" role – never admin, never pos
        rol = db.session.execute(db.select(Role).filter_by(name="apoderado")).scalar_one_or_none()
        if not rol:
            rol = Role(name="apoderado", description="Apoderado del Casino")
            db.session.add(rol)
            db.session.flush()

        hoy = date.today()
        creados = 0
        cursos = _get_cursos()  # fetch once per generation call, not per apoderado

        for _ in range(cantidad):
            primer_nombre = fake.first_name()
            apellido = fake.last_name()
            nombre_completo = f"{primer_nombre} {apellido}"

            # Chilean phone number format (9XXXXXXXX) as username
            username = f"9{fake.numerify('########')}"
            dominio = random.choice(["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"])
            email = f"{primer_nombre.lower()}.{apellido.lower()}{random.randint(1, 9999)}@{dominio}"

            if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
                continue  # skip on unlikely collision

            # 1. User (confirmed, active, role=apoderado only)
            user = User()
            user.email = email
            user.username = username
            user.password = hash_password("TestPass2024!")
            user.active = True
            user.confirmed_at = _hora_escolar_aleatoria(
                hoy - timedelta(days=random.randint(30, 365)), "general"
            )
            user.fs_uniquifier = str(uuid.uuid4())
            user.roles = [rol]
            db.session.add(user)
            db.session.flush()

            # 2. Apoderado
            n_alumnos = random.randint(1, 3)  # realistic: no family has 34 kids
            max_diario = random.choice([None, 2000, 3000, 5000])
            max_semanal = random.choice([None, 10000, 15000])
            apoderado = Apoderado(
                nombre=nombre_completo,
                alumnos_registro=n_alumnos,
                usuario=user,
                saldo_cuenta=0,
                maximo_diario=max_diario,
                maximo_semanal=max_semanal,
                notificacion_compra=True,
            )
            db.session.add(apoderado)
            db.session.flush()

            # 3. Alumnos — same apellido, different first names, real Chilean courses
            for _ in range(n_alumnos):
                a_nombre = f"{fake.first_name()} {apellido}"
                a_slug = _slugify(f"{a_nombre}-{random.randint(1000, 9999)}")
                alumno = Alumno(
                    slug=a_slug,
                    nombre=a_nombre,
                    curso=random.choice(cursos),
                    activo=True,
                    apoderado=apoderado,
                    maximo_diario=max_diario,
                    maximo_semanal=max_semanal,
                    restricciones=_restricciones_aleatorias(random),
                )
                db.session.add(alumno)

            # 4. Abonos spread over the last 90 school days — some fail, most succeed
            saldo = 0
            for _ in range(random.randint(1, 4)):
                dias_atras = random.randint(1, 90)
                fecha_abono = hoy - timedelta(days=dias_atras)
                # Weekends are fine — a parent paying via Khipu at 2 AM on Saturday is normal
                dt_abono = _hora_escolar_aleatoria(fecha_abono, "abono")
                codigo_abono = str(uuid.uuid4())
                monto = random.choice([5000, 10000, 15000, 20000, 25000, 30000])
                forma_pago = random.choice(["transferencia", "khipu", "efectivo"])

                abono = Abono(
                    codigo=codigo_abono,
                    monto=Decimal(monto),
                    apoderado=apoderado,
                    descripcion="Abono de Prueba",
                    forma_pago=forma_pago,
                )
                abono.created = dt_abono
                db.session.add(abono)

                # Payment created at the same moment the parent initiated it (any hour)
                # but if it was validated ("succeeded") that only happens during office hours
                estado_pago = random.choices(
                    ["succeeded", "processing", "failed", "cancelled"],
                    weights=[60, 25, 10, 5],
                )[0]
                if estado_pago == "succeeded":
                    # Admin validated the payment the next weekday during office hours
                    dt_validacion = _hora_escolar_aleatoria(
                        fecha_abono + timedelta(days=1), "validacion"
                    )
                else:
                    dt_validacion = dt_abono
                payment = Payment(
                    session_id=codigo_abono,
                    redirect_url="https://example.cl/pago",
                    provider="cafeteria" if forma_pago == "efectivo" else forma_pago,
                    amount=Decimal(monto),
                    currency="CLP",
                    state=estado_pago,
                    metadata_json={"apoderado_id": apoderado.id, "monto": monto},
                    request_payload={"amount": str(monto), "currency": "CLP"},
                    response_payload={},
                )
                payment.created_at = dt_abono
                payment.updated_at = dt_validacion
                db.session.add(payment)

                if estado_pago == "succeeded":
                    saldo += monto

            apoderado.saldo_cuenta = saldo
            creados += 1

        db.session.commit()
        return creados

    def _generar_menus_diarios(self, fake, cantidad: int) -> int:
        import random
        from datetime import date, timedelta
        from decimal import Decimal

        from slugify import slugify as _slugify

        platos = db.session.execute(db.select(Plato).where(Plato.activo.is_(True))).scalars().all()
        if not platos:
            flash("No hay Platos disponibles. Crea Platos primero.", "error")
            return 0

        entradas = [p for p in platos if any(p.nombre.lower().startswith(kw) for kw in ("sopa", "crema", "ensalada", "consomé", "empanada", "humita", "pebre"))]
        fondos = [p for p in platos if p not in entradas and not any(p.nombre.lower().startswith(kw) for kw in ("arroz con leche", "leche asada", "kuchen", "mote", "sopaipilla", "gelatina", "flan", "picarones", "fruta", "torta"))]
        postres = [p for p in platos if p not in entradas and p not in fondos]

        if not entradas:
            entradas = platos
        if not fondos:
            fondos = platos
        if not postres:
            postres = platos

        existing_slugs = {
            row[0]
            for row in db.session.execute(db.select(MenuDiario.slug)).all()
        }

        creados = 0
        start_date = date.today() + timedelta(days=1)

        for i in range(cantidad):
            dia = start_date + timedelta(days=i)
            slug_candidate = _slugify(f"menu-{dia.isoformat()}")
            if slug_candidate in existing_slugs:
                continue

            menu = MenuDiario(
                dia=dia,
                slug=slug_candidate,
                precio=Decimal(random.choice([2500, 3000, 3500, 4000, 4500])),
                activo=True,
                stock=random.randint(20, 100),
                es_permanente=False,
            )
            db.session.add(menu)
            db.session.flush()  # get menu.id

            # Add opciones: 1-2 entradas, 2-3 fondos, 1-2 postres
            orden = 0
            for plato in random.sample(entradas, min(random.randint(1, 2), len(entradas))):
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.ENTRADA, orden=orden))
                orden += 1
            for plato in random.sample(fondos, min(random.randint(2, 3), len(fondos))):
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.FONDO, orden=orden))
                orden += 1
            for plato in random.sample(postres, min(random.randint(1, 2), len(postres))):
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.POSTRE, orden=orden))
                orden += 1

            existing_slugs.add(slug_candidate)
            creados += 1

        db.session.commit()
        return creados

    @expose("/vaciar", methods=["POST"])
    def vaciar(self):
        """Delete all records of a single model, respecting FK order."""
        modelo = request.form.get("modelo", "")

        _VACIAR = {
            "plato": {
                "label": "Plato(s)",
                "pasos": [
                    (OpcionMenuDia, "asignación(es) de menú"),
                    (Plato, "plato(s)"),
                ],
            },
            "menu_diario": {
                "label": "Menú(s) Diario(s)",
                # cascade="all, delete-orphan" on MenuDiario.opciones handles OpcionMenuDia
                "pasos": [(MenuDiario, "menú(s) diario(s)")],
            },
            "apoderado": {
                "label": "Apoderado(s) + Alumnos + Abonos + Pagos",
                "pasos": [
                    (OrdenCasino, "orden(es) de casino"),
                    (Alumno, "alumno(s)"),
                    (Payment, "pago(s)"),
                    (Abono, "abono(s)"),
                    (Apoderado, "apoderado(s)"),
                ],
            },
            "alumno": {
                "label": "Alumno(s)",
                "pasos": [
                    (OrdenCasino, "orden(es) de casino"),
                    (Alumno, "alumno(s)"),
                ],
            },
            "abono": {
                "label": "Abono(s) + Pagos asociados",
                "pasos": [
                    (Payment, "pago(s)"),
                    (Abono, "abono(s)"),
                ],
            },
            "pedido": {
                "label": "Pedido(s)",
                "pasos": [
                    (OrdenCasino, "orden(es) de casino"),
                    (Pedido, "pedido(s)"),
                ],
            },
        }

        cfg = _VACIAR.get(modelo)
        if not cfg:
            flash(f"Modelo desconocido: {modelo!r}", "error")
            return redirect(url_for("generar_datos.index"))

        try:
            partes = []
            for modelo_cls, etiqueta in cfg["pasos"]:
                count = db.session.execute(db.delete(modelo_cls)).rowcount
                if count:
                    partes.append(f"{count} {etiqueta}")
            db.session.commit()
            resumen = ", ".join(partes) if partes else "0 registros"
            flash(f"🗑️ {cfg['label']} vaciado(s): {resumen} eliminado(s).", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Error al vaciar {cfg['label']}: {exc}", "error")

        return redirect(url_for("generar_datos.index"))


class GestorMenuView(BaseView):
    """Simplified menu and dish management view accessible to 'admin' or 'pos' roles.

    Provides three workflow options:
    1. Crear Plato Rápido  – add a new dish (Plato) with dietary flags.
    2. Crear Menú del Día  – create a new MenuDiario and assign existing Platos by course.
    3. Copiar Menú         – clone an existing MenuDiario to one or more new dates.
    """

    def is_accessible(self):
        return (
            current_user.is_active
            and current_user.is_authenticated
            and (current_user.has_role("admin") or current_user.has_role("pos"))
        )

    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        """Landing page – shows the 3 workflow cards."""
        platos = (
            db.session.execute(db.select(Plato).where(Plato.activo.is_(True)).order_by(Plato.nombre))
            .scalars()
            .all()
        )
        menus = (
            db.session.execute(db.select(MenuDiario).order_by(MenuDiario.dia.desc()).limit(30))
            .scalars()
            .all()
        )
        return self.render("admin/gestor_menu.html", platos=platos, menus=menus)

    @expose("/crear-plato", methods=["POST"])
    def crear_plato(self):
        """Option 1: quickly create a new Plato."""
        nombre = (request.form.get("nombre") or "").strip()
        if not nombre:
            flash("El nombre del plato no puede estar vacío.", "error")
            return redirect(url_for("gestor_menu.index"))

        existing = db.session.execute(db.select(Plato).filter_by(nombre=nombre)).scalar_one_or_none()
        if existing:
            flash(f"Ya existe un plato con el nombre «{nombre}».", "warning")
            return redirect(url_for("gestor_menu.index"))

        plato = Plato(
            nombre=nombre,
            activo=True,
            es_vegano=bool(request.form.get("es_vegano")),
            es_vegetariano=bool(request.form.get("es_vegetariano")),
            es_hipocalorico=bool(request.form.get("es_hipocalorico")),
            contiene_gluten=bool(request.form.get("contiene_gluten")),
            contiene_alergenos=bool(request.form.get("contiene_alergenos")),
        )
        db.session.add(plato)
        db.session.commit()
        flash(f"Plato «{nombre}» creado exitosamente.", "success")
        return redirect(url_for("gestor_menu.index"))

    @expose("/crear-menu", methods=["POST"])
    def crear_menu(self):
        """Option 2: create a new MenuDiario with dish assignments."""
        from datetime import date as _date
        from decimal import Decimal, InvalidOperation

        dia_str = (request.form.get("dia") or "").strip()
        if not dia_str:
            flash("Debes seleccionar una fecha para el menú.", "error")
            return redirect(url_for("gestor_menu.index"))
        try:
            dia = _date.fromisoformat(dia_str)
        except ValueError:
            flash("Fecha inválida.", "error")
            return redirect(url_for("gestor_menu.index"))

        precio_str = (request.form.get("precio") or "").strip()
        try:
            precio = Decimal(precio_str) if precio_str else None
        except InvalidOperation:
            flash("Precio inválido.", "error")
            return redirect(url_for("gestor_menu.index"))

        slug_candidate = slugify(f"menu-{dia.isoformat()}")
        existing_menu = db.session.execute(db.select(MenuDiario).filter_by(slug=slug_candidate)).scalar_one_or_none()
        if existing_menu:
            flash(f"Ya existe un menú para la fecha {dia.isoformat()} (slug: {slug_candidate}).", "warning")
            return redirect(url_for("gestor_menu.index"))

        descripcion = (request.form.get("descripcion") or "").strip() or None

        menu = MenuDiario(
            dia=dia,
            slug=slug_candidate,
            precio=precio,
            descripcion=descripcion,
            activo=True,
            stock=int(request.form.get("stock") or 50),
        )
        db.session.add(menu)
        db.session.flush()

        entradas_ids = request.form.getlist("entradas")
        fondos_ids = request.form.getlist("fondos")
        postres_ids = request.form.getlist("postres")

        orden = 0
        for plato_id in entradas_ids:
            plato = db.session.get(Plato, int(plato_id))
            if plato:
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.ENTRADA, orden=orden))
                orden += 1
        for plato_id in fondos_ids:
            plato = db.session.get(Plato, int(plato_id))
            if plato:
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.FONDO, orden=orden))
                orden += 1
        for plato_id in postres_ids:
            plato = db.session.get(Plato, int(plato_id))
            if plato:
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.POSTRE, orden=orden))
                orden += 1

        db.session.commit()
        flash(f"Menú para el {dia.strftime('%d/%m/%Y')} creado exitosamente.", "success")
        return redirect(url_for("gestor_menu.index"))

    @expose("/copiar-menu", methods=["POST"])
    def copiar_menu(self):
        """Option 3: clone an existing MenuDiario to new dates."""
        from datetime import date as _date

        menu_id_str = (request.form.get("menu_origen_id") or "").strip()
        fechas_raw = (request.form.get("fechas_destino") or "").strip()

        if not menu_id_str or not fechas_raw:
            flash("Debes seleccionar el menú origen y al menos una fecha destino.", "error")
            return redirect(url_for("gestor_menu.index"))

        try:
            menu_id = int(menu_id_str)
        except ValueError:
            flash("ID de menú inválido.", "error")
            return redirect(url_for("gestor_menu.index"))

        origen = db.session.get(MenuDiario, menu_id)
        if not origen:
            flash("Menú origen no encontrado.", "error")
            return redirect(url_for("gestor_menu.index"))

        fechas = [f.strip() for f in fechas_raw.split(",") if f.strip()]
        if not fechas:
            flash("Debes proporcionar al menos una fecha destino.", "error")
            return redirect(url_for("gestor_menu.index"))

        existing_slugs = {
            row[0]
            for row in db.session.execute(db.select(MenuDiario.slug)).all()
        }

        creados = 0
        omitidos = []
        for fecha_str in fechas:
            try:
                dia = _date.fromisoformat(fecha_str)
            except ValueError:
                omitidos.append(f"{fecha_str} (fecha inválida)")
                continue

            slug_candidate = slugify(f"menu-{dia.isoformat()}")
            if slug_candidate in existing_slugs:
                omitidos.append(f"{dia.isoformat()} (ya existe)")
                continue

            nuevo = MenuDiario(
                dia=dia,
                slug=slug_candidate,
                precio=origen.precio,
                descripcion=origen.descripcion,
                activo=origen.activo,
                stock=origen.stock,
                es_permanente=origen.es_permanente,
            )
            db.session.add(nuevo)
            db.session.flush()

            for opcion in origen.opciones:
                db.session.add(
                    OpcionMenuDia(
                        menu=nuevo,
                        plato=opcion.plato,
                        tipo_curso=opcion.tipo_curso,
                        orden=opcion.orden,
                    )
                )

            existing_slugs.add(slug_candidate)
            creados += 1

        db.session.commit()

        if creados:
            flash(f"Se copiaron {creados} menú(s) exitosamente.", "success")
        if omitidos:
            flash(f"Se omitieron {len(omitidos)} fecha(s): {', '.join(omitidos)}.", "warning")
        return redirect(url_for("gestor_menu.index"))


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
admin.add_view(GestorMenuView(name="Gestor de Menús", endpoint="gestor_menu", category="Casino"))


admin.add_view(UserView(User, db.session, category="Usuarios y Roles", name="Usuarios"))
admin.add_view(SecureModelView(Role, db.session, category="Usuarios y Roles", name="Roles"))
admin.add_menu_item(MenuDivider(), target_category="Usuarios y Roles")
admin.add_view(ApoderadoAdminView(Apoderado, db.session, category="Usuarios y Roles"))
admin.add_view(AlumnoAdminView(Alumno, db.session, category="Usuarios y Roles"))


admin.add_view(SecureModelView(Settings, db.session, name="Configuracion"))
admin.add_view(GenerarDatosView(name="Generar Datos", endpoint="generar_datos", category="Herramientas"))

admin.add_link(MenuLink(name="Sitio Web", endpoint="core.index", icon_type="glyph", icon_value="glyphicon-home"))
admin.add_link(MenuLink(name="POS", endpoint="pos.index", icon_type="glyph", icon_value="glyphicon-shopping-cart"))
admin.add_link(MenuLink(name="Apoderado", endpoint="apoderado_cliente.index", icon_type="glyph", icon_value="glyphicon-user"))
admin.add_link(MenuLink(name="Mi Cuenta", endpoint="security.change_password", icon_type="glyph", icon_value="glyphicon-cog"))
admin.add_link(MenuLink(name="Cerrar Sesión", endpoint="security.logout", icon_type="glyph", icon_value="glyphicon-log-out"))
