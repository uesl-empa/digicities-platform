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
from pathlib import Path

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
