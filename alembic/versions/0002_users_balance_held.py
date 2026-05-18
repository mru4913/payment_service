"""Add users.balance_held — denormalized sum of active task holds.

Revision ID: 0002_users_balance_held
Revises: 0001_initial_schema
Create Date: 2026-05-11

可用余额 = balance - balance_held（不存库）。回填：自 task_balance_holds active 汇总。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_users_balance_held"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "balance_held",
            sa.Numeric(15, 6),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE users AS u
        SET balance_held = COALESCE(
            (
                SELECT SUM(tbh.amount_usd)
                FROM task_balance_holds AS tbh
                WHERE tbh.telegram_id = u.telegram_id
                  AND tbh.status = 'active'
            ),
            0
        )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "balance_held")
