"""add live-progress fields to job_runs

Revision ID: c1a2b3d4e5f6
Revises: b7fd3fa35394
Create Date: 2026-07-25 20:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, None] = "b7fd3fa35394"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("files_total", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job_runs", sa.Column("bytes_total", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("job_runs", sa.Column("current_item", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_runs", "current_item")
    op.drop_column("job_runs", "bytes_total")
    op.drop_column("job_runs", "files_total")
