"""Rename tasks.charged_amount_usd -> charged_amount.

Revision ID: 0003_tasks_rename_charged_amount
Revises: 0002_users_balance_held
Create Date: 2026-05-08

币种仍为美元，仅字段名缩短；ORM 与 `Task.charged_amount` 对齐。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_tasks_rename_charged_amount"
down_revision: Union[str, None] = "0002_users_balance_held"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tasks",
        "charged_amount_usd",
        new_column_name="charged_amount",
        existing_type=sa.Numeric(15, 6),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "tasks",
        "charged_amount",
        new_column_name="charged_amount_usd",
        existing_type=sa.Numeric(15, 6),
        existing_nullable=True,
    )
