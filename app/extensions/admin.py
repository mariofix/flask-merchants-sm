import os
import os.path as op

from flask import flash, request, redirect, abort, url_for, current_app
from markupsafe import Markup, escape
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
from ..extensions import limiter
from ..model import (
    Alumno,
    Apoderado,
    EstadoPedido,
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
    SchoolStaff,
    SchoolStaffPedido,
)
from wtforms import SelectMultipleField
from flask_admin.form import Select2Widget
from wtforms import StringField
from wtforms.validators import Optional


def _read_recent_audit_entries(n: int = 20) -> list[str]:
    """Return the last *n* lines from the audit log file.

    The log path is read from ``current_app.config['AUDIT_LOG_PATH']`` when
    available, falling back to ``logs/audit.log``.
    """
    from flask import current_app

    log_path = current_app.config.get("AUDIT_LOG_PATH", os.path.join("logs", "audit.log"))
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
                .join(Payment, Payment.merchants_id == Abono.codigo)
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


def _alumno_tag_formatter(view, context, model, name):
    tag = model.tag
    if not tag:
        return ''
    safe_tag = escape(tag)
    return Markup(
        f'<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
        f'<div class="qr-code-container" data-tag="{safe_tag}"></div>'
        f'<small style="font-size:0.7em;word-break:break-all;text-align:center;'
        f'max-width:90px;font-family:monospace">{safe_tag}</small>'
        f'</div>'
    )


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

    column_formatters = {"tag": _alumno_tag_formatter}

    extra_js = [
        "/static/tabler/libs/qrcodejs/qrcode.min.js",
        "/static/tabler/js/alumno-qr-init.js",
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


def _abono_payment_state_formatter(view, context, model, name):
    if model.payment:
        return model.payment.state
    return "-"


class AbonoAdminView(SecureModelView):
    column_list = ["codigo", "apoderado", "monto", "forma_pago", "payment_state", "descripcion", "created"]
    column_formatters = {"payment_state": _abono_payment_state_formatter}
    column_labels = {"payment_state": "Estado Pago"}

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
            pago = db.session.execute(db.select(Payment).filter_by(merchants_id=abono.codigo)).scalar_one_or_none()
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
                send_notificacion_admin_abono(abono_info=abono_info)
            if abono.apoderado.comprobantes_transferencia:
                send_comprobante_abono(abono_info=abono_info)
                if abono.apoderado.copia_notificaciones:
                    send_copia_notificaciones_abono(abono_info=abono_info)
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
                send_comprobante_abono(abono_info=abono_info)
                send_notificacion_admin_abono(abono_info=abono_info)
                if abono.apoderado.comprobantes_transferencia and abono.apoderado.copia_notificaciones:
                    send_copia_notificaciones_abono(abono_info=abono_info)
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
                return "-"
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
                "curso": alumno.curso if alumno else "-",
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



class GestorMenuView(BaseView):
    """Simplified menu and dish management view accessible to 'admin' or 'pos' roles.

    Provides two workflow options:
    1. Crear Menú del Día  - create a new MenuDiario and assign existing Platos by course.
    2. Copiar Menú         - clone an existing MenuDiario to one or more new dates.
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

    def _obtiene_fotos(self):
        base = Path(settings.DIRECTORIO_FOTOS_PLATO)
        try:
            return sorted(
                f.name for f in base.iterdir() if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            )
        except (FileNotFoundError, PermissionError):
            return []

    def _get_platos_activos(self):
        return (
            db.session.execute(db.select(Plato).where(Plato.activo.is_(True)).order_by(Plato.nombre))
            .scalars()
            .all()
        )

    def _get_menus_recientes(self, limit: int = 30):
        return (
            db.session.execute(db.select(MenuDiario).order_by(MenuDiario.dia.desc()).limit(limit))
            .scalars()
            .all()
        )

    @expose("/", methods=["GET"])
    def index(self):
        """Landing page - shows the 3 workflow cards."""
        return self.render(
            "admin/gestor_menu.html",
            platos=self._get_platos_activos(),
            menus=self._get_menus_recientes(),
        )

    @expose("/crear-menu-dia", methods=["GET"])
    def crear_menu_dia_form(self):
        """Dedicated full-page form for creating a new MenuDiario (Option 1)."""
        from datetime import date as _date, timedelta

        platos = self._get_platos_activos()
        fotos = self._obtiene_fotos()
        # Suggest tomorrow as the default date
        default_dia = (_date.today() + timedelta(days=1)).isoformat()
        return self.render(
            "admin/crear_menu_dia.html",
            platos=platos,
            fotos=fotos,
            default_dia=default_dia,
        )

    @expose("/crear-menu", methods=["POST"])
    def crear_menu(self):
        """Option 1: create a new MenuDiario with dish assignments."""
        from datetime import date as _date
        from decimal import Decimal, InvalidOperation

        _form_redirect = url_for("gestor_menu.crear_menu_dia_form")

        dia_str = (request.form.get("dia") or "").strip()
        if not dia_str:
            flash("Debes seleccionar una fecha para el menú.", "error")
            return redirect(_form_redirect)
        try:
            dia = _date.fromisoformat(dia_str)
        except ValueError:
            flash("Fecha inválida.", "error")
            return redirect(_form_redirect)

        precio_str = (request.form.get("precio") or "").strip()
        try:
            precio = Decimal(precio_str) if precio_str else None
        except InvalidOperation:
            flash("Precio inválido.", "error")
            return redirect(_form_redirect)

        descripcion = (request.form.get("descripcion") or "").strip() or None
        if not descripcion:
            flash("La descripción es obligatoria para el menú.", "error")
            return redirect(_form_redirect)

        slug_candidate = slugify(descripcion)
        existing_menu = db.session.execute(db.select(MenuDiario).filter_by(slug=slug_candidate)).scalar_one_or_none()
        if existing_menu:
            flash(f"Ya existe un menú con la descripción «{descripcion}» (slug: {slug_candidate}).", "warning")
            return redirect(_form_redirect)

        foto_str = (request.form.get("foto") or "").strip() or None
        foto_principal = [foto_str] if foto_str else None

        menu = MenuDiario(
            dia=dia,
            slug=slug_candidate,
            precio=precio,
            descripcion=descripcion,
            foto_principal=foto_principal,
            activo=True,
            stock=int(request.form.get("stock") or 50),
            es_permanente=False,
        )
        db.session.add(menu)
        db.session.flush()

        entrada_id = (request.form.get("entradas") or "").strip()
        fondo_id = (request.form.get("fondos") or "").strip()
        postre_id = (request.form.get("postres") or "").strip()

        orden = 0
        if entrada_id:
            plato = db.session.get(Plato, int(entrada_id))
            if plato:
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.ENTRADA, orden=orden))
                orden += 1
        if fondo_id:
            plato = db.session.get(Plato, int(fondo_id))
            if plato:
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.FONDO, orden=orden))
                orden += 1
        if postre_id:
            plato = db.session.get(Plato, int(postre_id))
            if plato:
                db.session.add(OpcionMenuDia(menu=menu, plato=plato, tipo_curso=TipoCurso.POSTRE, orden=orden))
                orden += 1

        db.session.commit()
        flash(f"Menú para el {dia.strftime('%d/%m/%Y')} creado exitosamente.", "success")
        return redirect(url_for("gestor_menu.index"))

    @expose("/copiar-menu", methods=["POST"])
    def copiar_menu(self):
        """Option 2: clone an existing MenuDiario to new dates."""
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

            slug_candidate = slugify(f"{origen.descripcion or origen.slug}-{dia.isoformat()}")
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


class PaymentAdminView(SecureModelView):
    """Extended Flask-Admin view for Payment with app-specific post-payment actions.

    Extends the base SecureModelView with:
    - Overridden 'Sync from Provider' action that also triggers post-payment business
      logic (OrdenCasino creation, saldo credit, email notifications) when a payment
      transitions to 'succeeded'.
    - New 'Confirmar Pago' action for manually marking payments as succeeded and
      recording the admin action in ``response_payload``.
    """

    column_list = ["merchants_id", "transaction_id", "provider", "amount", "currency", "state", "created_at", "updated_at"]
    column_searchable_list = ["merchants_id", "transaction_id", "provider"]
    column_filters = ["state", "provider", "currency"]
    column_default_sort = ("created_at", True)

    def __init__(self, model, session, *, ext=None, **kwargs):
        self._ext = ext
        super().__init__(model, session, **kwargs)

    def _post_payment_processing(self, pago: Payment, admin_user: str | None = None, action_name: str | None = None) -> None:
        """Run post-payment business logic after a payment is marked as succeeded.

        Handles Abono (credit apoderado saldo), Pedido (create OrdenCasino records),
        and SchoolStaffPedido (mark staff pedido paid) cases.

        When *admin_user* and *action_name* are provided (manual admin action), a note
        is appended to ``response_payload`` in the form::

            {"payment_manual_action": "Paid by <user>, from Action [<name>], on <datetime>"}
        """
        from datetime import datetime as _datetime
        from flask_merchants import merchants_audit

        # Append manual action audit note when triggered by an admin
        if admin_user is not None and action_name is not None:
            note = {
                "payment_manual_action": (
                    f"Paid by {admin_user}, from Action [{action_name}], "
                    f"on {_datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            }
            current_payload = pago.response_payload
            if isinstance(current_payload, list):
                updated_payload = list(current_payload) + [note]
            elif isinstance(current_payload, dict) and current_payload:
                updated_payload = [current_payload, note]
            else:
                updated_payload = [note]
            pago.response_payload = updated_payload
            db.session.commit()

        # --- Abono: credit the apoderado's account balance ---
        abono = db.session.execute(
            db.select(Abono).filter_by(codigo=pago.merchants_id)
        ).scalar_one_or_none()
        if abono:
            from ..tasks import send_comprobante_abono, send_notificacion_admin_abono, send_copia_notificaciones_abono

            saldo_actual = abono.apoderado.saldo_cuenta or 0
            nuevo_saldo = saldo_actual + int(abono.monto)
            abono.apoderado.saldo_cuenta = nuevo_saldo
            # Populate payment_object with to_dict (avoiding recursive loop)
            # plus saldo snapshot before/after credit
            obj = pago.to_dict()
            obj.pop("payment_object", None)
            obj["saldo_antes"] = saldo_actual
            obj["saldo_despues"] = nuevo_saldo
            pago.payment_object = obj
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
            if abono.forma_pago != "cafeteria":
                send_notificacion_admin_abono(abono_info=abono_info)
            if abono.apoderado.comprobantes_transferencia:
                send_comprobante_abono(abono_info=abono_info)
                if abono.apoderado.copia_notificaciones:
                    send_copia_notificaciones_abono(abono_info=abono_info)
            return

        # --- Pedido (Apoderado): create OrdenCasino records and notify ---
        pedido = db.session.execute(
            db.select(Pedido).filter_by(codigo_merchants=pago.merchants_id)
        ).scalar_one_or_none()
        if pedido:
            from ..apoderado.controller import ApoderadoController

            pedido.pagado = True
            pedido.estado = EstadoPedido.PAGADO
            pedido.fecha_pago = _datetime.now()
            # Populate payment_object (avoiding recursive loop)
            obj = pago.to_dict()
            obj.pop("payment_object", None)
            pago.payment_object = obj
            db.session.commit()
            merchants_audit.info(
                "pedido_aprobado: codigo=%s monto=%s",
                pedido.codigo,
                int(pedido.precio_total),
            )
            ApoderadoController().process_payment_completion(pedido)
            return

        # --- SchoolStaffPedido: mark staff pedido paid and notify ---
        staff_pedido = db.session.execute(
            db.select(SchoolStaffPedido).filter_by(codigo_merchants=pago.merchants_id)
        ).scalar_one_or_none()
        if staff_pedido:
            from ..staff.controller import SchoolStaffController

            merchants_audit.info(
                "staff_pedido_aprobado: codigo=%s monto=%s",
                staff_pedido.codigo,
                int(staff_pedido.precio_total),
            )
            SchoolStaffController().process_payment_completion(staff_pedido)

    @action("sync", "Sync from Provider", "¿Sincronizar los pagos seleccionados con el proveedor?")
    def action_sync(self, ids: list) -> None:
        """Fetch live payment status from the provider.

        When a payment transitions to 'succeeded', post-payment business logic is
        triggered automatically (OrdenCasino creation, saldo credit, emails).
        """
        if self._ext is None:
            flash("Extensión FlaskMerchants no configurada; no se puede sincronizar.", "danger")
            return

        try:
            synced = 0
            failed = 0
            processed = 0
            for pk in ids:
                record = self.get_one(pk)
                if record is None:
                    continue
                old_state = record.state
                try:
                    status = self._ext.client.payments.get(record.transaction_id)
                    new_state = status.state.value
                    record.state = new_state
                    self.session.commit()
                    synced += 1
                    # Trigger post-payment logic when payment just completed
                    if new_state == "succeeded" and old_state in ("pending", "processing"):
                        self._post_payment_processing(record)
                        processed += 1
                except Exception as exc:  # noqa: BLE001
                    from flask_merchants import merchants_audit
                    merchants_audit.warning(
                        "sync_action_error: merchants_id=%r error=%s",
                        getattr(record, "merchants_id", pk),
                        exc,
                    )
                    failed += 1
            msg = f"{synced} pago(s) sincronizado(s) con el proveedor."
            if processed:
                msg += f" {processed} pago(s) procesado(s) como completados."
            if failed:
                msg += f" {failed} pago(s) no pudieron sincronizarse (ver log de auditoría)."
            flash(msg, "success" if not failed else "warning")
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            flash(f"Error al sincronizar pagos: {exc}", "danger")

    @action(
        "confirmar_pago",
        "Confirmar Pago",
        "¿Confirmar manualmente los pagos seleccionados? Se ejecutará el proceso post-pago.",
    )
    def action_confirmar_pago(self, ids: list) -> None:
        """Manually confirm selected payments and run post-payment business logic.

        Only payments in ``'pending'`` or ``'processing'`` state are processed.
        A note is appended to each payment's ``response_payload`` recording the
        admin user, action name, and timestamp.
        """
        confirmed = 0
        skipped = 0
        admin_username = str(current_user)

        for pk in ids:
            record = self.get_one(pk)
            if record is None:
                continue
            if record.state not in ("pending", "processing"):
                flash(
                    f"Pago {record.merchants_id[:8].upper()} no está en estado pendiente "
                    f"o procesando (estado actual: {record.state}).",
                    "warning",
                )
                skipped += 1
                continue
            record.state = "succeeded"
            self.session.commit()
            self._post_payment_processing(record, admin_user=admin_username, action_name="Confirmar Pago")
            confirmed += 1

        if confirmed:
            flash(f"{confirmed} pago(s) confirmado(s) exitosamente.", "success")


class SchoolStaffAdminView(SecureModelView):
    """Flask-Admin view for SchoolStaff (personal del colegio)."""

    column_list = ["nombre", "usuario", "limite_cuenta", "informe_semanal", "created"]
    column_labels = {
        "nombre": "Nombre",
        "usuario": "Usuario",
        "limite_cuenta": "Límite de Cuenta",
        "informe_semanal": "Informe Semanal",
        "created": "Creado",
    }


class SchoolStaffPedidoAdminView(SecureModelView):
    """Flask-Admin view for SchoolStaffPedido (pedidos del personal)."""

    column_list = ["codigo", "staff", "estado", "precio_total", "tipo_pago", "pagado", "fecha_pedido"]
    column_labels = {
        "codigo": "Código",
        "staff": "Personal",
        "estado": "Estado",
        "precio_total": "Precio Total",
        "tipo_pago": "Tipo de Pago",
        "pagado": "Pagado",
        "fecha_pedido": "Fecha Pedido",
    }
    column_filters = ["estado", "pagado", "tipo_pago"]
    column_default_sort = ("fecha_pedido", True)


class OrdenAdminView(BaseView):
    """Flask-Admin view that replaces the former /pos/orden-admin route.

    Provides a form to create a direct (no-payment) lunch order for a student,
    equivalent to the removed POS blueprint endpoints.
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
        """Render the direct admin order form."""
        from datetime import date as _date

        cursos_setting = db.session.execute(
            db.select(Settings).filter_by(slug="cursos")
        ).scalar_one_or_none()
        cursos = cursos_setting.value if cursos_setting and cursos_setting.value else []
        today_date = _date.today().isoformat()
        return self.render("admin/orden_admin.html", cursos=cursos, today_date=today_date)

    @expose("/create", methods=["POST"])
    @limiter.limit("60 per minute")
    def create(self):
        """Process the direct admin order form submission."""
        from datetime import date as _date
        from ..pos.crud import PosController

        ctrl = PosController()

        nombre = request.form.get("nombre_alumno", "").strip()
        curso = request.form.get("curso_alumno", "").strip()
        fecha_str = request.form.get("fecha", "").strip()
        menu_slug = request.form.get("menu_slug", "").strip()
        correo = request.form.get("correo", "").strip()
        phone = request.form.get("phone", "").strip()

        if not nombre or not curso or not fecha_str or not menu_slug:
            flash("Nombre, curso, fecha y menú son obligatorios.", "danger")
            return redirect(url_for("orden_admin.index"))

        try:
            fecha = _date.fromisoformat(fecha_str)
        except ValueError:
            flash("Fecha inválida.", "danger")
            return redirect(url_for("orden_admin.index"))

        nota_parts = []
        if correo:
            nota_parts.append(f"correo: {correo}")
        if phone:
            nota_parts.append(f"tel: {phone}")
        nota = ", ".join(nota_parts)[:255] if nota_parts else None

        try:
            orden = ctrl.crear_orden_admin(
                nombre_alumno=nombre,
                curso_alumno=curso,
                fecha=fecha,
                menu_slug=menu_slug,
                nota=nota,
            )
            flash(
                f"Orden creada para {orden.alumno.nombre} — {orden.menu_descripcion} ({fecha_str}).",
                "success",
            )
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("orden_admin.index"))

class GenerarDatosView(BaseView):
    """Flask-Admin view for generating and clearing test data using Faker.

    Provides two POST endpoints:
    - ``generar``: creates fake records for a chosen model using context-aware
      Spanish-locale data.
    - ``vaciar``: deletes all rows for a chosen model (Users and Roles are
      always left untouched).
    """

    def is_accessible(self):
        return (
            current_user.is_active
            and current_user.is_authenticated
            and current_user.has_role("admin")
        )

    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for("security.login", next=request.url))

    def _get_conteos(self) -> dict:
        from sqlalchemy import func as sa_func
        return {
            "Usuarios": db.session.execute(db.select(sa_func.count()).select_from(User)).scalar() or 0,
            "Apoderados": db.session.execute(db.select(sa_func.count()).select_from(Apoderado)).scalar() or 0,
            "Alumnos": db.session.execute(db.select(sa_func.count()).select_from(Alumno)).scalar() or 0,
            "Abonos": db.session.execute(db.select(sa_func.count()).select_from(Abono)).scalar() or 0,
            "Pedidos": db.session.execute(db.select(sa_func.count()).select_from(Pedido)).scalar() or 0,
            "Platos": db.session.execute(db.select(sa_func.count()).select_from(Plato)).scalar() or 0,
            "Menús Diarios": db.session.execute(db.select(sa_func.count()).select_from(MenuDiario)).scalar() or 0,
            "Órdenes Casino": db.session.execute(db.select(sa_func.count()).select_from(OrdenCasino)).scalar() or 0,
            "Pagos": db.session.execute(db.select(sa_func.count()).select_from(Payment)).scalar() or 0,
        }

    @expose("/", methods=["GET"])
    def index(self):
        return self.render("admin/generar_datos.html", conteos=self._get_conteos())

    @expose("/generar", methods=["POST"])
    def generar(self):
        """Generate fake records for the selected model."""
        from faker import Faker
        import random
        import uuid as _uuid
        from datetime import datetime as _dt, timedelta

        fake = Faker("es_CL")
        modelo = request.form.get("modelo", "plato")
        try:
            cantidad = min(max(int(request.form.get("cantidad", 10)), 1), 100)
        except (ValueError, TypeError):
            cantidad = 10

        cursos = ["1A", "1B", "2A", "2B", "3A", "3B", "4A", "4B", "5A", "5B", "6A", "6B",
                  "7A", "7B", "8A", "8B", "I-A", "I-B", "II-A", "II-B", "III-A", "III-B", "IV-A", "IV-B"]

        try:
            if modelo == "plato":
                ingredientes = [
                    "Pollo al horno", "Filete de merluza", "Lomo a lo pobre", "Cerdo asado",
                    "Salmón grillado", "Cazuela de vacuno", "Charquicán", "Porotos con riendas",
                    "Lentejas guisadas", "Garbanzos en salsa", "Arroz con leche", "Flan de vainilla",
                    "Ensalada de temporada", "Sopa de fideos", "Crema de zapallo",
                ]
                # Business rule: carnivore dishes are never marked as vegan
                carnivore_keywords = {"pollo", "filete", "lomo", "cerdo", "salmón", "vacuno", "merluza"}
                for _ in range(cantidad):
                    nombre = random.choice(ingredientes) + f" {fake.word()}"
                    nombre_lower = nombre.lower()
                    es_carnico = any(k in nombre_lower for k in carnivore_keywords)
                    plato = Plato()
                    plato.nombre = nombre[:255]
                    plato.activo = random.random() > 0.1
                    plato.es_vegano = False if es_carnico else random.random() > 0.8
                    plato.es_vegetariano = False if es_carnico else random.random() > 0.6
                    plato.es_hipocalorico = random.random() > 0.7
                    plato.contiene_gluten = random.random() > 0.3
                    plato.contiene_alergenos = random.random() > 0.6
                    db.session.add(plato)
                db.session.commit()
                flash(f"Se generaron {cantidad} plato(s).", "success")

            elif modelo == "apoderado":
                for _ in range(cantidad):
                    apellido = fake.last_name()
                    nombre_completo = f"{fake.first_name()} {apellido}"
                    email = f"{slugify(nombre_completo)}.{fake.numerify('###')}@{fake.free_email_domain()}"
                    user = User()
                    user.email = email
                    user.username = f"+569{fake.numerify('########')}"
                    user.password = fake.password()
                    user.active = True
                    user.fs_uniquifier = str(_uuid.uuid4())
                    db.session.add(user)
                    db.session.flush()

                    apoderado = Apoderado()
                    apoderado.nombre = nombre_completo
                    apoderado.alumnos_registro = random.randint(1, 3)
                    apoderado.usuario = user
                    apoderado.saldo_cuenta = random.choice([0, 5000, 10000, 15000, 20000])
                    db.session.add(apoderado)
                    db.session.flush()

                    # 1-3 alumnos sharing the same surname
                    for i in range(apoderado.alumnos_registro):
                        alumno = Alumno()
                        alumno.nombre = f"{fake.first_name()} {apellido}"
                        curso = random.choice(cursos)
                        alumno.curso = curso
                        alumno.slug = slugify(f"{alumno.nombre}-{curso}-{fake.numerify('###')}")
                        alumno.apoderado = apoderado
                        alumno.activo = True
                        alumno.restricciones = []
                        db.session.add(alumno)

                    # 1-3 abonos (can be at any time)
                    for _ in range(random.randint(1, 3)):
                        abono = Abono()
                        abono.monto = random.choice([5000, 10000, 15000, 20000, 25000])
                        abono.apoderado = apoderado
                        abono.descripcion = "Abono generado"
                        abono.forma_pago = random.choice(["transferencia", "efectivo"])
                        db.session.add(abono)

                db.session.commit()
                flash(f"Se generaron {cantidad} apoderado(s) con sus alumnos y abonos.", "success")

            elif modelo == "alumno":
                apoderados = db.session.execute(db.select(Apoderado)).scalars().all()
                if not apoderados:
                    flash("No existen apoderados. Genera algunos primero.", "warning")
                else:
                    for _ in range(cantidad):
                        apoderado = random.choice(apoderados)
                        alumno = Alumno()
                        alumno.nombre = f"{fake.first_name()} {fake.last_name()}"
                        curso = random.choice(cursos)
                        alumno.curso = curso
                        alumno.slug = slugify(f"{alumno.nombre}-{curso}-{fake.numerify('###')}")
                        alumno.apoderado = apoderado
                        alumno.activo = True
                        alumno.restricciones = []
                        db.session.add(alumno)
                    db.session.commit()
                    flash(f"Se generaron {cantidad} alumno(s).", "success")

            elif modelo == "menu_diario":
                platos = db.session.execute(db.select(Plato).filter_by(activo=True)).scalars().all()
                if not platos:
                    flash("No existen platos activos. Genera algunos primero.", "warning")
                else:
                    from datetime import date as _date
                    for i in range(cantidad):
                        fecha = _date.today() + timedelta(days=i + 1)
                        menu = MenuDiario()
                        menu.dia = fecha
                        menu.slug = slugify(f"menu-{fecha.isoformat()}-{fake.numerify('###')}")
                        menu.descripcion = f"Menú {fecha.strftime('%A %d/%m')}"
                        menu.precio = random.choice([3500, 4000, 4500, 5000])
                        menu.activo = True
                        menu.fuera_stock = False
                        menu.es_permanente = False
                        db.session.add(menu)
                        db.session.flush()

                        for tipo in TipoCurso:
                            disponibles = [p for p in platos]
                            if disponibles:
                                opcion = OpcionMenuDia()
                                opcion.menu = menu
                                opcion.plato = random.choice(disponibles)
                                opcion.tipo_curso = tipo
                                db.session.add(opcion)

                    db.session.commit()
                    flash(f"Se generaron {cantidad} menú(s) diario(s).", "success")

            else:
                flash(f"Modelo desconocido: {modelo!r}", "warning")

        except Exception as exc:
            db.session.rollback()
            flash(f"Error al generar datos: {exc}", "error")

        return redirect(url_for("generar_datos.index"))

    @expose("/vaciar", methods=["POST"])
    def vaciar(self):
        """Delete all records for the selected model."""
        modelo = request.form.get("modelo", "")
        try:
            if modelo == "plato":
                db.session.execute(db.delete(OpcionMenuDia))
                count = db.session.execute(db.delete(Plato)).rowcount
                db.session.commit()
                flash(f"Se eliminaron {count} plato(s) y sus asignaciones.", "success")

            elif modelo == "menu_diario":
                count = db.session.execute(db.delete(MenuDiario)).rowcount
                db.session.commit()
                flash(f"Se eliminaron {count} menú(s) diario(s) y sus opciones.", "success")

            elif modelo == "apoderado":
                db.session.execute(db.delete(OrdenCasino))
                db.session.execute(db.delete(Payment))
                db.session.execute(db.delete(Abono))
                db.session.execute(db.delete(Pedido))
                db.session.execute(db.delete(Alumno))
                count = db.session.execute(db.delete(Apoderado)).rowcount
                db.session.commit()
                flash(f"Se eliminaron {count} apoderado(s) con alumnos, abonos y pagos.", "success")

            elif modelo == "alumno":
                db.session.execute(db.delete(OrdenCasino))
                count = db.session.execute(db.delete(Alumno)).rowcount
                db.session.commit()
                flash(f"Se eliminaron {count} alumno(s) y sus órdenes de casino.", "success")

            elif modelo == "abono":
                count = db.session.execute(db.delete(Abono)).rowcount
                db.session.commit()
                flash(f"Se eliminaron {count} abono(s).", "success")

            elif modelo == "pedido":
                db.session.execute(db.delete(OrdenCasino))
                count = db.session.execute(db.delete(Pedido)).rowcount
                db.session.commit()
                flash(f"Se eliminaron {count} pedido(s) y sus órdenes de casino.", "success")

            else:
                flash(f"Modelo desconocido: {modelo!r}", "warning")

        except Exception as exc:
            db.session.rollback()
            flash(f"Error al vaciar: {exc}", "error")

        return redirect(url_for("generar_datos.index"))


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
admin.add_view(SchoolStaffPedidoAdminView(SchoolStaffPedido, db.session, category="Casino", name="Pedidos Personal"))
admin.add_view(OrdenAdminView(name="Orden Directa", endpoint="orden_admin", category="Casino"))
admin.add_view(ResumenDiaAdminView(name="Resumen del Día", endpoint="resumen_dia", category="Casino"))
admin.add_view(GestorMenuView(name="Gestor de Menús", endpoint="gestor_menu", category="Casino"))


admin.add_view(UserView(User, db.session, category="Usuarios y Roles", name="Usuarios"))
admin.add_view(SecureModelView(Role, db.session, category="Usuarios y Roles", name="Roles"))
admin.add_menu_item(MenuDivider(), target_category="Usuarios y Roles")
admin.add_view(ApoderadoAdminView(Apoderado, db.session, category="Usuarios y Roles"))
admin.add_view(AlumnoAdminView(Alumno, db.session, category="Usuarios y Roles"))
admin.add_view(SchoolStaffAdminView(SchoolStaff, db.session, category="Usuarios y Roles", name="Personal del Colegio"))


admin.add_view(SecureModelView(Settings, db.session, name="Configuracion"))
admin.add_view(GenerarDatosView(name="Generar Datos de Prueba", endpoint="generar_datos"))

admin.add_link(MenuLink(name="Sitio Web", endpoint="core.index", icon_type="glyph", icon_value="glyphicon-home"))
admin.add_link(MenuLink(name="POS", endpoint="pos.index", icon_type="glyph", icon_value="glyphicon-shopping-cart"))
admin.add_link(MenuLink(name="Apoderado", endpoint="apoderado_cliente.index", icon_type="glyph", icon_value="glyphicon-user"))
admin.add_link(MenuLink(name="Mi Cuenta", endpoint="security.change_password", icon_type="glyph", icon_value="glyphicon-cog"))
admin.add_link(MenuLink(name="Cerrar Sesión", endpoint="security.logout", icon_type="glyph", icon_value="glyphicon-log-out"))
