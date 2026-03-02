"""Create merchants_payment table

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "merchants_payment" not in inspector.get_table_names():
        op.create_table(
            "merchants_payment",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("redirect_url", sa.String(length=2048), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("request_payload", sa.JSON(), nullable=False),
            sa.Column("response_payload", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_merchants_payment")),
        )
        with op.batch_alter_table("merchants_payment", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_merchants_payment_session_id"),
                ["session_id"],
                unique=True,
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "merchants_payment" in inspector.get_table_names():
        with op.batch_alter_table("merchants_payment", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_merchants_payment_session_id"))
        op.drop_table("merchants_payment")
