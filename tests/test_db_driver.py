# SPDX-License-Identifier: Apache-2.0
"""The metadata database always uses the driver the image ships (psycopg2).

SQLAlchemy 2.1 changed the default driver for a bare ``postgresql://`` URL from
psycopg2 to psycopg (v3). A rebuild that resolved 2.1 took sign-in and the
workspace list down on live (``No module named 'psycopg'``). The URL now names
the driver, so the default no longer matters.
"""
from __future__ import annotations

import pytest

from backend.db import session


@pytest.mark.parametrize("raw", [
    "postgresql://u:p@postgres:5432/digicities",
    "postgres://u:p@postgres:5432/digicities",
])
def test_a_bare_postgres_url_names_psycopg2(monkeypatch, raw):
    monkeypatch.setenv("DATABASE_URL", raw)
    assert session.database_url() == "postgresql+psycopg2://u:p@postgres:5432/digicities"


@pytest.mark.parametrize("raw", [
    "postgresql+psycopg://u:p@h/d",       # an explicit choice is kept
    "sqlite:///tmp/x.db",
])
def test_an_explicit_or_other_url_is_left_alone(monkeypatch, raw):
    monkeypatch.setenv("DATABASE_URL", raw)
    assert session.database_url() == raw


def test_no_url_means_no_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert session.database_url() is None


def test_the_resolved_dialect_is_psycopg2(monkeypatch):
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from sqlalchemy.engine import make_url
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    assert make_url(session.database_url()).get_dialect().driver == "psycopg2"
