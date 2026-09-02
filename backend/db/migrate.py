# SPDX-License-Identifier: Apache-2.0
"""Schema management. Prefer Alembic migrations; on an existing/legacy DB (tables already
created via create_all) or any Alembic hiccup, fall back to create_all + stamp head so future
migrations still apply. No-op when the DB is disabled."""
from __future__ import annotations

from pathlib import Path


def _config():
    from alembic.config import Config
    from .session import database_url
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url() or "")
    return cfg


def ensure_schema() -> None:
    from .session import engine
    if engine() is None:
        return                                  # DB disabled → nothing to do
    from alembic import command
    try:
        command.upgrade(_config(), "head")
    except Exception:
        # Legacy DB (tables exist, no alembic_version) or Alembic problem: guarantee the
        # tables exist, then stamp head so subsequent revisions apply cleanly.
        from .workspaces_repo import init_db
        init_db()
        try:
            command.stamp(_config(), "head")
        except Exception:
            pass
