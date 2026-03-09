"""Refactor PaymentMixin: rename columns, add transaction_id, add indexes

in sqlite3
update alembic_version version_num='a7b8c9d0e1f2';
Revision ID: a7b8c9d0e1f2
Revises: 1c659aae9e49
Create Date: 2026-03-08 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "1c659aae9e49"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("merchants_payment", schema=None) as batch_op:
        # Rename session_id -> merchants_id
        batch_op.alter_column("session_id", new_column_name="merchants_id")

        # Rename provider_payment_object -> payment_object
        batch_op.alter_column("provider_payment_object", new_column_name="payment_object")

        # Change currency from String(8) to String(3)
        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=8),
            type_=sa.String(length=3),
            existing_nullable=False,
        )

        # Add transaction_id column (nullable initially for existing rows)
        batch_op.add_column(
            sa.Column("transaction_id", sa.String(length=128), nullable=True)
        )

        # Drop redirect_url column
        batch_op.drop_column("redirect_url")

        # Add server_default to request_payload and response_payload
        batch_op.alter_column(
            "request_payload",
            existing_type=sa.JSON(),
            server_default=sa.text("'{}'"),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "response_payload",
            existing_type=sa.JSON(),
            server_default=sa.text("'{}'"),
            existing_nullable=False,
        )

        # Add new indexes
        batch_op.create_index(
            batch_op.f("ix_merchants_payment_provider"), ["provider"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_merchants_payment_state"), ["state"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_merchants_payment_email"), ["email"], unique=False
        )

    # Backfill transaction_id from merchants_id for existing rows
    op.execute("UPDATE merchants_payment SET transaction_id = merchants_id WHERE transaction_id IS NULL")

    with op.batch_alter_table("merchants_payment", schema=None) as batch_op:
        # Now make transaction_id non-nullable
        batch_op.alter_column(
            "transaction_id",
            existing_type=sa.String(length=128),
            nullable=False,
        )
        # Create unique index on transaction_id
        batch_op.create_index(
            batch_op.f("ix_merchants_payment_transaction_id"),
            ["transaction_id"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("merchants_payment", schema=None) as batch_op:
        # Drop new indexes
        batch_op.drop_index(batch_op.f("ix_merchants_payment_transaction_id"))
        batch_op.drop_index(batch_op.f("ix_merchants_payment_email"))
        batch_op.drop_index(batch_op.f("ix_merchants_payment_state"))
        batch_op.drop_index(batch_op.f("ix_merchants_payment_provider"))

        # Drop transaction_id column
        batch_op.drop_column("transaction_id")

        # Re-add redirect_url column
        batch_op.add_column(
            sa.Column("redirect_url", sa.String(length=2048), nullable=False, server_default="")
        )

        # Revert currency from String(3) to String(8)
        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=3),
            type_=sa.String(length=8),
            existing_nullable=False,
        )

        # Rename payment_object -> provider_payment_object
        batch_op.alter_column("payment_object", new_column_name="provider_payment_object")

        # Rename merchants_id -> session_id
        batch_op.alter_column("merchants_id", new_column_name="session_id")

        # Remove server_defaults from request_payload and response_payload
        batch_op.alter_column(
            "request_payload",
            existing_type=sa.JSON(),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "response_payload",
            existing_type=sa.JSON(),
            server_default=None,
            existing_nullable=False,
        )
