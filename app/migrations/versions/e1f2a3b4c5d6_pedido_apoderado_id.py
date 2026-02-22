"""Add apoderado_id FK to casino_pedido

Revision ID: e1f2a3b4c5d6
Revises: c1f4d2e83a9b
Create Date: 2026-02-22 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "c1f4d2e83a9b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("casino_pedido", schema=None) as batch_op:
        batch_op.add_column(sa.Column("apoderado_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_casino_pedido_apoderado_id"), ["apoderado_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_casino_pedido_apoderado_id_casino_apoderado"),
            "casino_apoderado",
            ["apoderado_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("casino_pedido", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_casino_pedido_apoderado_id_casino_apoderado"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_casino_pedido_apoderado_id"))
        batch_op.drop_column("apoderado_id")
