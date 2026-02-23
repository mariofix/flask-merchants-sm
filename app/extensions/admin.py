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
    Payment,
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
]

_PLATOS_FONDOS_VEGETARIANOS = [
    ("Tortilla de Acelga", False, True, True, False, True),
    ("Lasaña de Verduras", False, True, False, True, True),
    ("Revuelto Gramajo", False, True, False, False, True),
    ("Omelette con Queso y Tomate", False, True, True, False, True),
    ("Quiche de Espinacas", False, True, False, True, True),
    ("Fideos con Salsa de Tomate", False, True, False, True, False),
    ("Arroz con Leche de Coco", False, True, True, False, False),
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
]

_CURSOS_CHILENOS = [
    "1° Básico A", "1° Básico B", "2° Básico A", "2° Básico B",
    "3° Básico A", "3° Básico B", "4° Básico A", "4° Básico B",
    "5° Básico A", "5° Básico B", "6° Básico A", "6° Básico B",
    "7° Básico A", "7° Básico B", "8° Básico A", "8° Básico B",
    "1° Medio A", "1° Medio B", "2° Medio A", "2° Medio B",
    "3° Medio A", "3° Medio B", "4° Medio A", "4° Medio B",
]


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

        flash(f"✅ Se crearon {creados} registros de tipo «{modelo}» exitosamente.", "success")
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
        for _ in range(cantidad):
            nombre = f"{fake.first_name()} {fake.last_name()}"
            curso = random.choice(_CURSOS_CHILENOS)
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
            )
            db.session.add(alumno)
            creados += 1

        db.session.commit()
        return creados

    def _generar_apoderados(self, fake, cantidad: int) -> int:
        import random

        # Find users that don't already have an apoderado
        existing_apoderado_user_ids = {
            row[0]
            for row in db.session.execute(db.select(Apoderado.usuario_id)).all()
        }
        usuarios = [
            u for u in db.session.execute(db.select(User)).scalars().all()
            if u.id not in existing_apoderado_user_ids
        ]
        if not usuarios:
            flash("No hay Usuarios disponibles sin Apoderado. Crea Usuarios primero.", "error")
            return 0

        creados = 0
        for usuario in usuarios[:cantidad]:
            apoderado = Apoderado(
                nombre=f"{fake.first_name()} {fake.last_name()}",
                alumnos_registro=random.randint(1, 3),
                usuario=usuario,
                saldo_cuenta=random.randint(0, 50000),
                maximo_diario=random.choice([None, 2, 3]),
                maximo_semanal=random.choice([None, 10, 15]),
            )
            db.session.add(apoderado)
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
            from ..model import TipoCurso
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
        """Delete all records except User and Role tables."""
        from ..model import Abono, Alumno, Apoderado, MenuDiario, OpcionMenuDia, OrdenCasino, Payment, Pedido, Plato, Settings

        # Order matters: delete dependents before parents
        tablas_orden = [
            OrdenCasino,
            OpcionMenuDia,
            MenuDiario,
            Abono,
            Alumno,
            Apoderado,
            Plato,
            Pedido,
            Payment,
            Settings,
        ]
        total = 0
        for modelo in tablas_orden:
            result = db.session.execute(db.delete(modelo))
            total += result.rowcount

        db.session.commit()
        flash(f"🗑️ Base de datos vaciada. Se eliminaron {total} registros (Usuarios y Roles conservados).", "success")
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
admin.add_view(ResumenDiaAdminView(name="Resumen del Día", endpoint="resumen_dia", category="Casino"))


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
