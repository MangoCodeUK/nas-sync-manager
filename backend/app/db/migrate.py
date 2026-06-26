"""Run Alembic migrations programmatically at startup.

Keeps Alembic as the single source of truth for the schema: a fresh database is
created by upgrading to head, and NAS updates apply any new revisions.
"""
from __future__ import annotations

import os

from alembic import command
from alembic.config import Config

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    return cfg


def upgrade_to_head() -> None:
    command.upgrade(_alembic_config(), "head")
