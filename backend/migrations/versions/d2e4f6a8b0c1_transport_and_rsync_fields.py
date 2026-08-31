"""add transport axis to jobs and rsync fields to connections

Purely additive, with defaults chosen so every existing row keeps its current
behaviour: jobs become transport="ftp", connections become rsync_enabled=False.
Nothing needs backfilling and no FTP column is touched.

Revision ID: d2e4f6a8b0c1
Revises: c1a2b3d4e5f6
Create Date: 2026-08-31 22:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e4f6a8b0c1"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- jobs: how bytes move, alongside what the job does ------------------
    op.add_column(
        "sync_jobs",
        sa.Column("transport", sa.String(length=8), nullable=False, server_default="ftp"),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("rsync_compress", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sync_jobs", sa.Column("rsync_bandwidth_kbps", sa.Integer(), nullable=True))

    # --- connections: a device may speak FTP, rsync, or both ----------------
    op.add_column("nas_connections", sa.Column("fs_root", sa.String(length=1024), nullable=True))
    op.add_column(
        "nas_connections",
        sa.Column("rsync_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "nas_connections",
        sa.Column("rsync_mode", sa.String(length=8), nullable=False, server_default="daemon"),
    )
    op.add_column("nas_connections", sa.Column("rsync_host", sa.String(length=255), nullable=True))
    op.add_column(
        "nas_connections",
        sa.Column("rsync_port", sa.Integer(), nullable=False, server_default="873"),
    )
    op.add_column("nas_connections", sa.Column("rsync_module", sa.String(length=255), nullable=True))
    op.add_column(
        "nas_connections", sa.Column("rsync_username", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "nas_connections", sa.Column("rsync_encrypted_password", sa.Text(), nullable=True)
    )
    op.add_column(
        "nas_connections",
        sa.Column("rsync_ssh_port", sa.Integer(), nullable=False, server_default="22"),
    )


def downgrade() -> None:
    for column in (
        "rsync_ssh_port",
        "rsync_encrypted_password",
        "rsync_username",
        "rsync_module",
        "rsync_port",
        "rsync_host",
        "rsync_mode",
        "rsync_enabled",
        "fs_root",
    ):
        op.drop_column("nas_connections", column)
    for column in ("rsync_bandwidth_kbps", "rsync_compress", "transport"):
        op.drop_column("sync_jobs", column)
