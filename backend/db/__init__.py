# SPDX-License-Identifier: Apache-2.0
"""Metadata database (Postgres) for the workspace catalog + (phase 2) users/ACL.

A thin SQLAlchemy layer. It is OPTIONAL: with no ``DATABASE_URL`` configured the
session/engine are None and every caller falls back to the filesystem registry, so
dev without Postgres is unaffected. Artifacts and the graph never live here — only
workspace metadata and (later) ownership.
"""
# NB: do not re-export the ``session`` function here — it would shadow the ``session``
# submodule (``backend.db.session``). Import it from the submodule where needed.
from .session import db_enabled, engine, database_url  # noqa: F401
