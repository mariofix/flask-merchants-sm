from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any, Optional

from flask_security.models import fsqla_v3 as fsqla
from sqlalchemy import JSON
from sqlalchemy import Date as SaDate
from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_utils.models import Timestamp
from werkzeug.utils import import_string


from flask_merchants.core import MerchantsError
from flask_merchants.mixins import IntegrationMixin, PaymentMixin

from .database import db


class Role(db.Model, fsqla.FsRoleMixin):
    def __str__(self):
        return f"{self.name}"


class User(db.Model, fsqla.FsUserMixin):
    apoderado: Mapped["Apoderado"] = relationship(back_populates="usuario")

    def __str__(self):
        return f"{self.username}"


class Integration(db.Model, IntegrationMixin):
    __tablename__ = "merchants_integrations"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Relationship to payments
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        primaryjoin="and_(Integration.slug == foreign(Payment.integration_slug))",
        viewonly=True,
        back_populates="integration",
    )

    def __str__(self):
        # From IntegrationMixin
        return f"{self.slug}"


class Payment(db.Model, PaymentMixin):
    __tablename__ = "merchants_payment"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Relationship to integration
    integration: Mapped[Optional["Integration"]] = relationship(
        "Integration",
        primaryjoin="and_(Integration.slug == foreign(Payment.integration_slug))",
        viewonly=True,
        back_populates="payments",
    )

    def __str__(self):
        # From PaymentMixin
        return f"{self.merchants_token}"

    def process(self):
        if not self.integration:
            raise MerchantsError(f"Integration: {self.integration_slug} does not exist.")

        if not self.integration.is_active:
            raise MerchantsError(f"Integration: {self.integration_slug} is not active.")

        try:
            integration = import_string(self.integration.integration_class)
            provider = integration()
            return provider.create(payload=self.merchants_payload())
        except MerchantsError as err:
            raise err


# Casino
class Abono(db.Model, Timestamp):
    __tablename__ = "casino_abono"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    forma_pago: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    apoderado_id: Mapped[int] = mapped_column(ForeignKey("casino_apoderado.id"))
    apoderado: Mapped["Apoderado"] = relationship(back_populates="abonos")

    def __str__(self):
        return f"{self.codigo}"

    def to_dict(self):
        return {"id": self.id, "codigo": self.codigo, "descripcion": self.descripcion, "monto": self.monto}


class Alumno(db.Model, Timestamp):
    ___tablename__ = "casino_alumno"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=False)
    curso: Mapped[str | None] = mapped_column(String(255), nullable=False)
    activo: Mapped[bool] = mapped_column(default=True)
    motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    apoderado_id: Mapped[int] = mapped_column(ForeignKey("casino_apoderado.id"))
    apoderado: Mapped["Apoderado"] = relationship(back_populates="alumnos")

    maximo_diario: Mapped[int] = mapped_column(default=None, nullable=True)
    maximo_semanal: Mapped[int] = mapped_column(default=None, nullable=True)

    tag_compartido: Mapped[bool] = mapped_column(default=False)

    restricciones: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __str__(self):
        return f"{self.slug}"

    def nombre_alumno(self):
        return f"{self.nombre}"


class Apoderado(db.Model, Timestamp):
    __tablename__ = "casino_apoderado"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=False)
    alumnos_registro: Mapped[int] = mapped_column(default=0, nullable=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    usuario: Mapped["User"] = relationship(back_populates="apoderado")

    comprobantes_transferencia: Mapped[bool] = mapped_column(default=False)
    notificacion_compra: Mapped[bool] = mapped_column(default=True)
    informe_semanal: Mapped[bool] = mapped_column(default=False)
    tag_compartido: Mapped[bool] = mapped_column(default=False)
    copia_notificaciones: Mapped[str | None] = mapped_column(String(255), nullable=True)

    maximo_diario: Mapped[int] = mapped_column(default=None, nullable=True)
    maximo_semanal: Mapped[int] = mapped_column(default=None, nullable=True)

    saldo_cuenta: Mapped[int] = mapped_column(default=None, nullable=True)
    limite_notificacion: Mapped[int] = mapped_column(default=1500)

    alumnos: Mapped[list["Alumno"]] = relationship(back_populates="apoderado")
    abonos: Mapped[list["Abono"]] = relationship(back_populates="apoderado", order_by=Abono.created.desc())

    def __str__(self):
        return f"{self.usuario.username}"


class TipoCurso(PyEnum):
    ENTRADA = "entrada"
    FONDO = "fondo"
    POSTRE = "postre"


class Plato(db.Model, Timestamp):
    __tablename__ = "casino_plato"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    activo: Mapped[bool] = mapped_column(default=True)
    es_vegano: Mapped[bool] = mapped_column(default=False)
    es_vegetariano: Mapped[bool] = mapped_column(default=False)
    es_hipocalorico: Mapped[bool] = mapped_column(default=False)
    contiene_gluten: Mapped[bool] = mapped_column(default=True)
    contiene_alergenos: Mapped[bool] = mapped_column(default=False)

    opciones_menu: Mapped[list["OpcionMenuDia"]] = relationship(back_populates="plato")

    def __str__(self):
        return self.nombre


class MenuDiario(db.Model, Timestamp):
    __tablename__ = "casino_menu_dia"

    id: Mapped[int] = mapped_column(primary_key=True)
    dia: Mapped[date] = mapped_column(SaDate, index=True, nullable=False)
    es_permanente: Mapped[bool] = mapped_column(default=True, nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    opciones: Mapped[list["OpcionMenuDia"]] = relationship(
        back_populates="menu",
        cascade="all, delete-orphan",
        order_by="OpcionMenuDia.tipo_curso, OpcionMenuDia.orden",
    )

    precio: Mapped[Decimal | None] = mapped_column(Numeric(10, 0), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    extra_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    foto_principal: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=list)
    activo: Mapped[bool] = mapped_column(default=True)

    @property
    def entradas(self) -> list["Plato"]:
        return [op.plato for op in self.opciones if op.tipo_curso == TipoCurso.ENTRADA]

    @property
    def fondos(self) -> list["Plato"]:
        return [op.plato for op in self.opciones if op.tipo_curso == TipoCurso.FONDO]

    @property
    def postres(self) -> list["Plato"]:
        return [op.plato for op in self.opciones if op.tipo_curso == TipoCurso.POSTRE]

    def __str__(self):
        return f"{self.dia.strftime('%A %d/%m')} - {self.slug}"


class OpcionMenuDia(db.Model, Timestamp):
    """Opciones específicas por curso para cada día"""

    __tablename__ = "casino_opcion_menu_dia"

    id: Mapped[int] = mapped_column(primary_key=True)

    menu_id: Mapped[int] = mapped_column(ForeignKey("casino_menu_dia.id"))
    menu: Mapped["MenuDiario"] = relationship(back_populates="opciones")

    plato_id: Mapped[int] = mapped_column(ForeignKey("casino_plato.id"))
    plato: Mapped["Plato"] = relationship(back_populates="opciones_menu")

    tipo_curso: Mapped[TipoCurso] = mapped_column(Enum(TipoCurso), nullable=False)
    orden: Mapped[int] = mapped_column(default=0)

    def __str__(self):
        return f"{self.tipo_curso.value}: {self.plato.nombre}"


## Tienda


# class Category(db.Model, Timestamp):
#     __tablename__ = "store_category"
#     id: Mapped[int] = mapped_column(primary_key=True)
#     slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
#     name: Mapped[str | None] = mapped_column(String(255), nullable=False)
#     active: Mapped[bool] = mapped_column(default=True)

#     # Relationship
#     products: Mapped[list["Product"]] = relationship(back_populates="category")

#     def __str__(self):
#         return f"{self.slug}"


# class ProductType(db.Model, Timestamp):
#     __tablename__ = "store_product_type"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
#     name: Mapped[str | None] = mapped_column(String(255), nullable=False)

#     # Relationship
#     products: Mapped[list["Product"]] = relationship(back_populates="product_type")

#     def __str__(self):
#         return f"{self.slug}"


# class Branch(db.Model, Timestamp):
#     __tablename__ = "store_branch"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
#     name: Mapped[str] = mapped_column(String(255), nullable=False)
#     active: Mapped[bool] = mapped_column(default=True)
#     extra_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

#     # Foreign Key
#     partner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)

#     # Relationships
#     partner: Mapped["User"] = relationship(back_populates="branches")
#     products: Mapped[list["Product"]] = relationship(secondary="store_branch_product", back_populates="branches")

#     def __str__(self):
#         return f"{self.slug}"


# # Association table for Branch-Product many-to-many
# class BranchProduct(db.Model):
#     __tablename__ = "store_branch_product"

#     branch_id: Mapped[int] = mapped_column(ForeignKey("store_branch.id"), primary_key=True)
#     product_id: Mapped[int] = mapped_column(ForeignKey("store_product.id"), primary_key=True)
#     price_override: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

#     active: Mapped[bool] = mapped_column(default=True)


# # Update Product model
# class Product(db.Model, Timestamp):
#     __tablename__ = "store_product"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
#     name: Mapped[str | None] = mapped_column(String(255), nullable=False)
#     description: Mapped[str | None] = mapped_column(String(2048), nullable=True)
#     price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
#     currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")
#     active: Mapped[bool] = mapped_column(default=True)
#     extra_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

#     # Foreign Keys
#     category_id: Mapped[int] = mapped_column(ForeignKey("store_category.id"), nullable=False, index=True)
#     product_type_id: Mapped[int] = mapped_column(ForeignKey("store_product_type.id"), nullable=False, index=True)

#     # Relationships
#     category: Mapped["Category"] = relationship(back_populates="products")
#     product_type: Mapped["ProductType"] = relationship(back_populates="products")
#     branches: Mapped[list["Branch"]] = relationship(secondary="store_branch_product", back_populates="products")

#     def __str__(self):
#         return f"{self.name}"


class Settings(db.Model, Timestamp):
    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[None | int] = mapped_column(ForeignKey("user.id"), nullable=True, default=None)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship()

    def __str__(self):
        return f"{self.slug} - {self.user_id}"


# class Student(db.Model, Timestamp):
#     __tablename__ = "store_student"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     parent_id: Mapped[None | int] = mapped_column(ForeignKey("user.id"), nullable=True, default=None)
#     name: Mapped[str] = mapped_column(String(255), nullable=False)

#     daily_limit: Mapped[int] = mapped_column()
#     weekly_limit: Mapped[int] = mapped_column()

#     user: Mapped["User"] = relationship(back_populates="students")


# ## Lector


# class Operador(db.Model, Timestamp):
#     __tablename__ = "reader_operator"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     nombre: Mapped[str] = mapped_column(String(255), nullable=False)
#     codigo_qr: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
#     en_turno: Mapped[bool] = mapped_column(default=True)
#     linea: Mapped[int]


# class lecturas(db.Model, Timestamp):
#     __tablename__ = "reader_readings"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     codigo_qr: Mapped[str]
#     linea: Mapped[int]
#     camara: Mapped[int]

import uuid
from enum import Enum as PyEnum


class EstadoPedido(PyEnum):
    CREADO = "creado"
    PENDIENTE = "pendiente"
    PAGADO = "pagado"
    CONFIRMADA = "confirmado"
    ENTREGADO_PARCIAL = "entregado-parcial"
    ENTREGADO = "entregado"
    COMPLETADO = "completado"
    CANCELADA = "cancelada"


class TipoPago(PyEnum):
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    TARJETA = "tarjeta"


class Pedido(db.Model, Timestamp):
    """Pedido de comida de un usuario"""

    __tablename__ = "casino_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False)
    codigo_merchants: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True, index=True)

    # Estado y tracking
    estado: Mapped[EstadoPedido] = mapped_column(Enum(EstadoPedido), default=EstadoPedido.CREADO)
    fecha_pedido: Mapped[datetime] = mapped_column(default=datetime.now(), index=True)
    fecha_pago: Mapped[datetime | None] = mapped_column(nullable=True)

    # Pago
    precio_total: Mapped[Decimal] = mapped_column(Numeric(10, 0), nullable=False)
    tipo_pago: Mapped[TipoPago] = mapped_column(Enum(TipoPago), nullable=False, default=TipoPago.EFECTIVO)
    pagado: Mapped[bool] = mapped_column(default=False)

    # Metadata
    extra_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __str__(self):
        return f"{self.codigo} - {self.estado.value}"
