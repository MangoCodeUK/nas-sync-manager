"""add the proportional delete guard and per-run transport/exit audit

Additive, with defaults that make existing rows behave as before. The 10%
default for max_delete_percent is deliberately a real limit rather than 100:
the absolute limits already default to 0 (nothing auto-deletes), so this only
ever becomes the binding constraint once someone raises those.

Revision ID: e3f5a7b9c2d4
Revises: d2e4f6a8b0c1
Create Date: 2026-08-31 23:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f5a7b9c2d4"
down_revision: Union[str, None] = "d2e4f6a8b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("max_delete_percent", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column("job_runs", sa.Column("transport", sa.String(length=8), nullable=True))
    op.add_column("job_runs", sa.Column("exit_code", sa.Integer(), nullable=True))
    op.add_column("job_runs", sa.Column("safety_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_runs", "safety_notes")
    op.drop_column("job_runs", "exit_code")
    op.drop_column("job_runs", "transport")
    op.drop_column("app_settings", "max_delete_percent")
