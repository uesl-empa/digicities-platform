# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Architecture invariants for the backend/UI split.

``backend/`` is the headless platform: it must be importable and usable with
no UI framework installed, by any frontend (Streamlit today, the React app via
apps/api). A single ``import streamlit`` sneaking in silently couples every
consumer to the Streamlit runtime, so the rule is enforced here rather than
left as a convention.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+streamlit\b|from\s+streamlit\b)", re.MULTILINE)


def _touches_session_state(source: str) -> bool:
    """True when code (not docstrings/comments) reads `st.session_state`."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and node.attr == "session_state"
                and isinstance(node.value, ast.Name)
                and node.value.id == "st"):
            return True
    return False


def _py_files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_backend_never_imports_streamlit():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _py_files(REPO_ROOT / "backend")
        if _IMPORT_RE.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "backend/ must stay UI-framework-free; streamlit imported in: "
        f"{offenders}"
    )


def test_backend_never_touches_session_state():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _py_files(REPO_ROOT / "backend")
        if _touches_session_state(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "backend/ must not reach into Streamlit session state: "
        f"{offenders}"
    )


def test_backend_never_imports_apps():
    """The dependency arrow points one way: apps → backend, never back."""
    pattern = re.compile(r"^\s*(?:import\s+apps\b|from\s+apps\b)", re.MULTILINE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _py_files(REPO_ROOT / "backend")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"backend/ must not import from apps/: {offenders}"


def test_api_never_imports_streamlit_tree():
    """The REST API must run without the Streamlit app on the path at all.

    Reaching into ``apps.streamlit.components`` (or its bare ``components``
    spelling) couples the API to the Streamlit runtime — any shared logic
    belongs in ``backend/``, imported by both frontends.
    """
    pattern = re.compile(
        r"^\s*(?:import\s+apps\.streamlit\b|from\s+apps\.streamlit\b"
        r"|import\s+components\b|from\s+components\b)",
        re.MULTILINE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _py_files(REPO_ROOT / "apps" / "api")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "apps/api must not import from the Streamlit tree; move the logic to "
        f"backend/ instead: {offenders}"
    )


def test_api_imports_without_streamlit():
    """``apps.api.main`` must import in a process where streamlit cannot.

    The static check above catches direct imports; this one catches the
    indirect kind — a backend module the API pulls in that itself imports
    streamlit. A meta-path blocker makes any streamlit import raise, then the
    whole API app is imported for real in a subprocess.
    """
    pytest.importorskip("fastapi")
    code = textwrap.dedent("""
        import importlib.abc
        import sys

        class BlockStreamlit(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "streamlit" or name.startswith("streamlit."):
                    raise ImportError("streamlit is blocked: the API must not need it")
                return None

        sys.meta_path.insert(0, BlockStreamlit())
        import apps.api.main  # noqa: F401
        print("api imported without streamlit")
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )
    assert proc.returncode == 0, (
        "importing apps.api.main pulled in streamlit (or failed outright):\n"
        f"{proc.stderr}"
    )
