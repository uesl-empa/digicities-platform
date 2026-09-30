# SPDX-License-Identifier: Apache-2.0

"""Guard: production code must stay generic — no usecase vocabulary in logic.

The platform grew out of the wind-forecasting pilot, and pilot class names
leaked into production logic three times (a hardcoded component-type list in
the data-products TTL parser, a wind default graph URI in the GraphDB client,
wind-only assumption templates). All were removed in PR #68; this test keeps
them out.

Mechanics: every Python file under backend/ and apps/api is parsed to an AST
and every STRING CONSTANT is checked against the banned vocabulary. Comments
and docstrings are exempt by construction (comments never reach the AST;
docstrings are skipped explicitly) — wind may still ILLUSTRATE, it may never
DRIVE. Add to BANNED when a new usecase's vocabulary must not creep in; add
to ALLOWLIST only for files that are explicitly demo/seed content.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [REPO / "backend", REPO / "apps" / "api"]

# Usecase vocabulary that must never appear in a production string constant.
# Deliberately the CLASS/id forms (no spaces): prose like "Wind Turbine" in a
# UI description is illustration, `"WindTurbine"` in code is logic.
BANNED = (
    "WindTurbine",
    "GlobalWindAtlasSite",
    "WindPark",
    "Alkmaar",
    "wind_forecasting",
    "eolica",
    "windforecast",
    "demo_energy_simulator",
)

# Files whose PURPOSE is demo/seed content (each must say so in its docstring).
ALLOWLIST = {
    "backend/assumptions/assumption_types.py",   # marked DEMO seed content
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids of the Constant nodes that are docstrings (module/class/function)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def test_no_usecase_vocabulary_in_production_strings():
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel in ALLOWLIST:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                if id(node) in docstrings:
                    continue
                hits = [b for b in BANNED if b.lower() in node.value.lower()]
                if hits:
                    offenders.append(f"{rel}:{node.lineno} {hits} in {node.value[:80]!r}")
    assert not offenders, (
        "Usecase vocabulary found in production string constants — the platform "
        "must stay domain-generic. Either make the code generic (see PR #68 for "
        "the pattern) or, for deliberate demo/seed files, extend the ALLOWLIST "
        "with a docstring note:\n" + "\n".join(offenders))
