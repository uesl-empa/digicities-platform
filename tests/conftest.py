# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Shared test harness.

Single sys.path bootstrap for the whole suite: repo root (for ``backend.*``
and ``apps.*``) plus ``apps/streamlit`` (the app runs with that directory on
the path, so its components import each other as ``components.*``).
Individual test files must not touch sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "apps" / "streamlit"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def api_app():
    """The FastAPI app; skips when the apps/api extra isn't installed.

    Yields the app and clears any dependency_overrides a test installed,
    so ctx overrides can't leak between tests.
    """
    pytest.importorskip("fastapi")
    from apps.api.main import app

    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def api_client(api_app):
    from fastapi.testclient import TestClient

    with TestClient(api_app) as client:
        yield client
