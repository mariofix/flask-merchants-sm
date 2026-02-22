"""OrdenCasino - track lunch consumption per alumno

Revision ID: c1f4d2e83a9b
Revises: 48a837bfc45d
Create Date: 2026-02-22 08:30:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c1f4d2e83a9b"
down_revision = "48a837bfc45d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "casino_orden_casino",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_codigo", sa.String(length=36), nullable=False),
        sa.Column("alumno_id", sa.Integer(), nullable=False),
        sa.Column("menu_slug", sa.String(length=255), nullable=False),
        sa.Column("menu_descripcion", sa.String(length=2048), nullable=True),
        sa.Column("menu_precio", sa.Numeric(precision=10, scale=0), nullable=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("nota", sa.String(length=255), nullable=True),
        sa.Column(
            "estado",
            sa.Enum("PENDIENTE", "ENTREGADO", "CANCELADO", name="estadoalmuerzo"),
            nullable=False,
        ),
        sa.Column("fecha_entrega", sa.DateTime(), nullable=True),
        sa.Column("reagendado_de_id", sa.Integer(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alumno_id"],
            ["alumno.id"],
            name=op.f("fk_casino_orden_casino_alumno_id_alumno"),
        ),
        sa.ForeignKeyConstraint(
            ["reagendado_de_id"],
            ["casino_orden_casino.id"],
            name=op.f("fk_casino_orden_casino_reagendado_de_id_casino_orden_casino"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_casino_orden_casino")),
    )
    with op.batch_alter_table("casino_orden_casino", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_casino_orden_casino_alumno_id"), ["alumno_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_casino_orden_casino_fecha"), ["fecha"], unique=False)
        batch_op.create_index(batch_op.f("ix_casino_orden_casino_pedido_codigo"), ["pedido_codigo"], unique=False)


def downgrade():
    with op.batch_alter_table("casino_orden_casino", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_casino_orden_casino_pedido_codigo"))
        batch_op.drop_index(batch_op.f("ix_casino_orden_casino_fecha"))
        batch_op.drop_index(batch_op.f("ix_casino_orden_casino_alumno_id"))

    op.drop_table("casino_orden_casino")
    op.execute("DROP TYPE IF EXISTS estadoalmuerzo")
