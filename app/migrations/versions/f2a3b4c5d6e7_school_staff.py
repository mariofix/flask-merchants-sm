"""Add casino_staff and casino_staff_pedido tables

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-02-25 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "casino_staff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("limite_cuenta", sa.Integer(), nullable=True),
        sa.Column("informe_semanal", sa.Boolean(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["user.id"], name=op.f("fk_casino_staff_usuario_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_casino_staff")),
        sa.UniqueConstraint("usuario_id", name=op.f("uq_casino_staff_usuario_id")),
    )

    op.create_table(
        "casino_staff_pedido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=36), nullable=False),
        sa.Column("codigo_merchants", sa.String(length=36), nullable=True),
        sa.Column(
            "estado",
            sa.Enum(
                "CREADO", "PENDIENTE", "PAGADO", "CONFIRMADA", "ENTREGADO_PARCIAL",
                "ENTREGADO", "COMPLETADO", "CANCELADA",
                name="estadopedido",
            ),
            nullable=False,
        ),
        sa.Column("fecha_pedido", sa.DateTime(), nullable=False),
        sa.Column("fecha_pago", sa.DateTime(), nullable=True),
        sa.Column("precio_total", sa.Numeric(precision=10, scale=0), nullable=False),
        sa.Column(
            "tipo_pago",
            sa.Enum("EFECTIVO", "TRANSFERENCIA", "TARJETA", name="tipopago"),
            nullable=False,
        ),
        sa.Column("pagado", sa.Boolean(), nullable=False),
        sa.Column("extra_attrs", sa.JSON(), nullable=True),
        sa.Column("staff_id", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["casino_staff.id"],
            name=op.f("fk_casino_staff_pedido_staff_id_casino_staff"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_casino_staff_pedido")),
        sa.UniqueConstraint("codigo", name=op.f("uq_casino_staff_pedido_codigo")),
    )
    with op.batch_alter_table("casino_staff_pedido", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_casino_staff_pedido_codigo_merchants"), ["codigo_merchants"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_casino_staff_pedido_fecha_pedido"), ["fecha_pedido"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_casino_staff_pedido_staff_id"), ["staff_id"], unique=False
        )


def downgrade():
    with op.batch_alter_table("casino_staff_pedido", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_casino_staff_pedido_staff_id"))
        batch_op.drop_index(batch_op.f("ix_casino_staff_pedido_fecha_pedido"))
        batch_op.drop_index(batch_op.f("ix_casino_staff_pedido_codigo_merchants"))
    op.drop_table("casino_staff_pedido")
    op.drop_table("casino_staff")
