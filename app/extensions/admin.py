import os.path as op

from flask import flash
from flask_admin import Admin
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuDivider
from flask_admin.theme import Bootstrap4Theme
from slugify import slugify

from .. import settings
from ..database import db
from ..model import (
    Alumno,
    Apoderado,
    FotoPlato,
    MenuDiario,
    OpcionMenuDia,
    Orden,
    Plato,
    Role,
    Settings,
    User,
)

admin = Admin(
    name="Merchants Store",
    url="/data-manager",
    theme=Bootstrap4Theme(fluid=True, swatch="united"),
    category_icon_classes={
        "Menu": "fa fa-cog text-danger",
    },
)


class UserView(ModelView):
    can_view_details = True
    column_list = ["username", "email", "active", "roles"]


class FileView(FileAdmin):
    can_delete_dirs = False
    allowed_extensions = ("jpg", "jpeg", "png", "gif", "webp")
    upload_modal = False

    def on_file_upload(self, directory, path, filename):
        print(f"{directory=} {path=} {filename=} {op.basename(filename)=}")
        """Se ejecuta después de subir un archivo"""
        # Crear slug único
        nombre_base = op.basename(filename)
        slug_base = slugify(nombre_base)

        # Verificar si ya existe
        slug = slug_base
        contador = 1
        while FotoPlato.query.filter_by(slug=slug).first():
            slug = f"{slug_base}-{contador}"
            contador += 1

        # Crear FotoPlato
        foto = FotoPlato(slug=slug, archivo=nombre_base, plato_id=None)  # type: ignore

        db.session.add(foto)
        db.session.commit()

        flash(
            f'Foto "{filename}" subida y registrada. Asóciala a un plato desde el editor.',
            "success",
        )

    def on_file_delete(self, full_path, filename):
        """Se ejecuta antes de eliminar un archivo"""
        # Buscar y eliminar el registro FotoPlato
        foto = FotoPlato.query.filter_by(archivo=filename).first()
        if foto:
            db.session.delete(foto)
            db.session.commit()
            flash(f'Registro de foto "{filename}" eliminado.', "info")


class PlatoAdminView(ModelView):
    column_list = [
        "nombre",
        "activo",
        "es_vegano",
        "es_vegetariano",
        "es_hipocalorico",
        "contiene_gluten",
        "fotos",
    ]


admin.add_view(PlatoAdminView(Plato, db.session, category="Casino"))
admin.add_view(
    FileView(
        settings.DIRECTORIO_FOTOS_PLATO,
        "/static/platos/",
        name="Administrador de Archivos",
        category="Casino",
    )
)
admin.add_view(ModelView(MenuDiario, db.session, category="Casino"))
admin.add_view(ModelView(OpcionMenuDia, db.session, category="Casino"))
admin.add_view(ModelView(Orden, db.session, category="Casino"))

admin.add_view(UserView(User, db.session, category="Usuarios y Roles", name="Usuarios"))
admin.add_view(ModelView(Role, db.session, category="Usuarios y Roles", name="Roles"))
admin.add_menu_item(MenuDivider(), target_category="Usuarios y Roles")
admin.add_view(ModelView(Apoderado, db.session, category="Usuarios y Roles"))
admin.add_view(ModelView(Alumno, db.session, category="Usuarios y Roles"))


# admin.add_view(ModelView(Product, db.session, category="Store"))
# admin.add_view(ModelView(ProductType, db.session, category="Store"))
# admin.add_view(ModelView(Category, db.session, category="Store"))


# admin.add_view(ModelView(Branch, db.session, name="Branches", category="Settings"))
# admin.add_view(ModelView(BranchProduct, db.session, name="Branch Product", category="Settings"))
admin.add_view(ModelView(Settings, db.session, name="Configuracion"))


# class PedidoView(BaseView):
#     """Vista para que usuarios hagan pedidos del menú del día"""

#     @expose("/", methods=["GET", "POST"])
#     # @login_required
#     def index(self):
#         # Obtener menú del día seleccionado o hoy
#         dia_seleccionado = request.args.get("dia", date.today().isoformat())
#         dia = date.fromisoformat(dia_seleccionado)

#         menu = MenuDiario.query.filter_by(dia=dia).first()

#         if not menu:
#             flash(f'No hay menú disponible para {dia.strftime("%d/%m/%Y")}', "warning")
#             return self.render("casino/no_menu.html", dia=dia)

#         # Verificar si ya tiene orden para este día
#         orden_existente = Orden.query.filter(Orden.menu_id == menu.id).first()

#         if request.method == "POST":
#             return self._procesar_pedido(menu, orden_existente)

#         # Agrupar opciones por tipo de curso
#         opciones_agrupadas = {}
#         for opcion in menu.opciones:
#             tipo = opcion.tipo_curso.value
#             if tipo not in opciones_agrupadas:
#                 opciones_agrupadas[tipo] = []
#             opciones_agrupadas[tipo].append(opcion)

#         return self.render(
#             "casino/hacer_pedido.html",
#             menu=menu,
#             opciones_agrupadas=opciones_agrupadas,
#             orden_existente=orden_existente,
#         )

#     def _procesar_pedido(self, menu, orden_existente):
#         try:
#             # Obtener selecciones del formulario
#             entrada_id = request.form.get("entrada")
#             fondo_id = request.form.get("fondo")
#             postre_id = request.form.get("postre")
#             vegetariano_id = request.form.get("vegetariano")
#             notas = request.form.get("notas", "").strip()
#             tipo_pago = request.form.get("tipo_pago", "descuento_planilla")

#             selecciones_ids = [int(x) for x in [entrada_id, fondo_id, postre_id, vegetariano_id] if x and x.isdigit()]

#             if not selecciones_ids:
#                 flash("Debes seleccionar al menos un plato", "error")
#                 return redirect(url_for(".index"))

#             # Validar que las opciones pertenecen al menú
#             opciones_validas = OpcionMenuDia.query.filter(
#                 OpcionMenuDia.id.in_(selecciones_ids), OpcionMenuDia.menu_id == menu.id
#             ).all()

#             if len(opciones_validas) != len(selecciones_ids):
#                 flash("Selección inválida", "error")
#                 return redirect(url_for(".index"))

#             # Crear o actualizar orden
#             if orden_existente:
#                 orden = orden_existente
#                 orden.updated_at = datetime.utcnow()
#                 # Limpiar selecciones anteriores
#                 for sel in orden.selecciones:
#                     db.session.delete(sel)
#                 mensaje = "Pedido actualizado exitosamente"
#             else:
#                 # Generar código único
#                 contador = Orden.query.filter(func.date(Orden.fecha_orden) == date.today()).count() + 1
#                 codigo = f"ORD-{date.today().strftime('%Y%m%d')}-{contador:03d}"

#                 orden = Orden(
#                     codigo=codigo,
#                     usuario_id=current_user.id,
#                     menu_id=menu.id,
#                     precio_total=menu.precio or 0,
#                     tipo_pago=TipoPago[tipo_pago.upper()],
#                     estado=EstadoOrden.PENDIENTE,
#                     notas_cliente=notas,
#                 )
#                 db.session.add(orden)
#                 mensaje = "Pedido realizado exitosamente"

#             # Agregar selecciones
#             for opcion in opciones_validas:
#                 seleccion = SeleccionOrden(
#                     orden=orden,
#                     opcion=opcion,
#                     plato_nombre=opcion.plato.nombre,
#                     tipo_curso=opcion.tipo_curso,
#                     cantidad=1,
#                 )
#                 db.session.add(seleccion)

#             db.session.commit()
#             flash(f"{mensaje}. Código: {orden.codigo}", "success")
#             return redirect(url_for("misordenes.index"))

#         except Exception as e:
#             db.session.rollback()
#             flash(f"Error al procesar pedido: {str(e)}", "error")
#             return redirect(url_for(".index"))


# class MisOrdenesView(BaseView):
#     """Vista para que usuarios vean sus pedidos"""

#     @expose("/")
#     # @login_required
#     def index(self):
#         ordenes = Orden.query.filter_by(usuario_id=current_user.id).order_by(Orden.fecha_orden.desc()).limit(30).all()

#         return self.render("casino/mis_ordenes.html", ordenes=ordenes)

#     @expose("/<int:orden_id>/cancelar", methods=["POST"])
#     # @login_required
#     def cancelar(self, orden_id):
#         orden = Orden.query.get_or_404(orden_id)

#         if orden.usuario_id != current_user.id:
#             flash("No autorizado", "error")
#             return redirect(url_for(".index"))

#         if orden.estado not in [EstadoOrden.PENDIENTE, EstadoOrden.CONFIRMADA]:
#             flash("No se puede cancelar esta orden", "error")
#             return redirect(url_for(".index"))

#         orden.estado = EstadoOrden.CANCELADA
#         db.session.commit()
#         flash("Orden cancelada", "success")
#         return redirect(url_for(".index"))


# admin.add_view(PedidoView(name="Hacer Pedido", endpoint="pedido", category="Casino"))
# admin.add_view(MisOrdenesView(name="Mis Órdenes", endpoint="misordenes", category="Casino"))
