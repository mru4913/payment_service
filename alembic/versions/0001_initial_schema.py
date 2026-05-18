"""Initial schema: users, payments, tasks, task_balance_holds, balance_transactions.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-08

task_balance_holds.task_id -> tasks.task_id ON DELETE CASCADE.
balance_transactions.task_id -> tasks.task_id ON DELETE SET NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "is_premium",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_scam",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_fake",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "balance",
            sa.Numeric(15, 6),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_deposits",
            sa.Numeric(15, 6),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_withdrawals",
            sa.Numeric(15, 6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("telegram_username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("telegram_id"),
    )
    op.create_index("idx_username", "users", ["telegram_username"], unique=False)
    op.create_index("idx_phone", "users", ["phone"], unique=False)
    op.create_index("idx_premium", "users", ["is_premium"], unique=False)
    op.create_index("idx_active", "users", ["is_active"], unique=False)

    op.create_table(
        "payments",
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(15, 6), nullable=False),
        sa.Column("payment_method", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("external_payment_id", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "payment_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(
            ["telegram_id"],
            ["users.telegram_id"],
        ),
        sa.PrimaryKeyConstraint("payment_id"),
    )
    op.create_index(
        "idx_payment_telegram_id",
        "payments",
        ["telegram_id"],
        unique=False,
    )
    op.create_index("idx_payment_status", "payments", ["status"], unique=False)
    op.create_index(
        "idx_payment_method_status",
        "payments",
        ["payment_method", "status"],
        unique=False,
    )
    op.create_index(
        "idx_payment_external_id",
        "payments",
        ["external_payment_id"],
        unique=False,
    )

    op.create_table(
        "tasks",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=True),
        sa.Column("third_party_platform", sa.String(length=32), nullable=False),
        sa.Column("priority_type", sa.String(length=32), nullable=False),
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("upstream_task_id", sa.String(length=128), nullable=True),
        sa.Column(
            "queued_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("billable_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("charged_amount_usd", sa.Numeric(15, 6), nullable=True),
        sa.Column("pricing_version", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["telegram_id"],
            ["users.telegram_id"],
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "idx_tasks_telegram_id_queued_at",
        "tasks",
        ["telegram_id", "queued_at"],
        unique=False,
    )
    op.create_index(
        "idx_tasks_status_queued_at",
        "tasks",
        ["status", "queued_at"],
        unique=False,
    )
    op.create_index(
        "idx_tasks_task_type_queued_at",
        "tasks",
        ["task_type", "queued_at"],
        unique=False,
    )
    op.create_index(
        "idx_tasks_third_party_upstream",
        "tasks",
        ["third_party_platform", "upstream_task_id"],
        unique=False,
    )
    op.create_index(
        "uq_tasks_telegram_idempotency_key",
        "tasks",
        ["telegram_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "task_balance_holds",
        sa.Column("hold_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(15, 6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("released_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("captured_amount_usd", sa.Numeric(15, 6), nullable=True),
        sa.ForeignKeyConstraint(["telegram_id"], ["users.telegram_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("hold_id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        "idx_tbh_telegram_id_status",
        "task_balance_holds",
        ["telegram_id", "status"],
        unique=False,
    )

    op.create_table(
        "balance_transactions",
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(15, 6), nullable=False),
        sa.Column("balance_before_usd", sa.Numeric(15, 6), nullable=False),
        sa.Column("balance_after_usd", sa.Numeric(15, 6), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.payment_id"]),
        sa.ForeignKeyConstraint(["telegram_id"], ["users.telegram_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_index(
        "idx_bt_telegram_id",
        "balance_transactions",
        ["telegram_id"],
        unique=False,
    )
    op.create_index(
        "idx_bt_payment_id",
        "balance_transactions",
        ["payment_id"],
        unique=False,
    )
    op.create_index(
        "idx_bt_task_id",
        "balance_transactions",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "idx_bt_transaction_type",
        "balance_transactions",
        ["transaction_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("balance_transactions")
    op.drop_table("task_balance_holds")
    op.drop_table("tasks")
    op.drop_table("payments")
    op.drop_table("users")
