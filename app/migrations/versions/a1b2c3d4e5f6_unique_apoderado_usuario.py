"""Add unique constraint on casino_apoderado.usuario_id

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-03-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("casino_apoderado") as batch_op:
        batch_op.create_unique_constraint(
            "uq_casino_apoderado_usuario_id",
            ["usuario_id"],
        )


def downgrade():
    with op.batch_alter_table("casino_apoderado") as batch_op:
        batch_op.drop_constraint(
            "uq_casino_apoderado_usuario_id",
            type_="unique",
        )
