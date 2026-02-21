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

import uuid
from enum import Enum as PyEnum

from flask_merchants.models import PaymentMixin

from .database import db


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


class Role(db.Model, fsqla.FsRoleMixin):
    def __str__(self):
        return f"{self.name}"


class User(db.Model, fsqla.FsUserMixin):
    apoderado: Mapped["Apoderado"] = relationship(back_populates="usuario")

    def __str__(self):
        return f"{self.username}"


class Payment(db.Model, PaymentMixin):
    __tablename__ = "merchants_payment"

    id: Mapped[int] = mapped_column(primary_key=True)

    def __str__(self):
        return f"{self.id}"


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

    tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    # opciones_menu: Mapped[list["OpcionMenuDia"]] = relationship(back_populates="plato")

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
    stock: Mapped[int] = mapped_column(default=1, server_default="1")
    fuera_stock: Mapped[bool] = mapped_column(default=False, nullable=True)

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
    plato: Mapped["Plato"] = relationship()

    tipo_curso: Mapped[TipoCurso] = mapped_column(Enum(TipoCurso), nullable=False)
    orden: Mapped[int] = mapped_column(default=0)

    def __str__(self):
        return f"{self.tipo_curso.value}: {self.plato.nombre}"


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
