# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Golden-file comparison helpers for characterization tests.

TTL goldens compare as RDF graphs (isomorphism), never as strings — emitter
output is not byte-stable across rdflib versions and dict orderings, and a
triple set is what actually has to be preserved. YAML/JSON goldens compare as
parsed structures for the same reason.

Re-record goldens intentionally with:  GOLDEN_UPDATE=1 pytest ...
A test run that (re)writes a golden fails on purpose, so an update can never
masquerade as a pass in CI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import rdflib
from rdflib.compare import graph_diff, to_isomorphic

GOLDENS_DIR = Path(__file__).resolve().parent / "goldens"

_UPDATE = os.getenv("GOLDEN_UPDATE", "").strip() not in ("", "0", "false")


def _golden_path(name: str) -> Path:
    path = GOLDENS_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _maybe_record(path: Path, content: str) -> None:
    if _UPDATE or not path.exists():
        # Path.write_text() only grew `newline=` in Python 3.10; open() has it
        # everywhere, and LF-only goldens must not vary with the recording OS.
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        pytest.fail(
            f"golden (re)recorded: {path.relative_to(GOLDENS_DIR.parent)} — "
            "inspect the diff, commit it, and re-run without GOLDEN_UPDATE"
        )


def _fmt_triples(graph: rdflib.Graph, limit: int = 12) -> str:
    lines = sorted(t.n3() for t in graph)  # type: ignore[attr-defined]
    shown = "\n    ".join(lines[:limit])
    extra = f"\n    … {len(lines) - limit} more" if len(lines) > limit else ""
    return "    " + shown + extra if lines else "    (none)"


def assert_ttl_golden(actual_ttl: str, name: str) -> None:
    """Assert `actual_ttl` is graph-isomorphic to the golden `name`."""
    path = _golden_path(name)
    _maybe_record(path, actual_ttl)

    actual = rdflib.Graph().parse(data=actual_ttl, format="turtle")
    golden = rdflib.Graph().parse(path.as_posix(), format="turtle")
    if to_isomorphic(actual) == to_isomorphic(golden):
        return
    _, only_actual, only_golden = graph_diff(
        to_isomorphic(actual), to_isomorphic(golden))
    pytest.fail(
        f"TTL output diverged from golden {name}\n"
        f"  triples only in actual output:\n{_fmt_triples(only_actual)}\n"
        f"  triples only in golden:\n{_fmt_triples(only_golden)}\n"
        f"  (re-record intentionally with GOLDEN_UPDATE=1)"
    )


def assert_yaml_golden(actual_yaml: str, name: str) -> None:
    """Assert `actual_yaml` parses to the same structure as the golden."""
    import yaml

    path = _golden_path(name)
    _maybe_record(path, actual_yaml)
    actual = yaml.safe_load(actual_yaml)
    golden = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert actual == golden, (
        f"YAML structure diverged from golden {name} "
        "(re-record intentionally with GOLDEN_UPDATE=1)"
    )


def assert_json_golden(actual: object, name: str) -> None:
    """Assert a JSON-serializable object equals the golden structure."""
    text = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False,
                      default=str) + "\n"
    path = _golden_path(name)
    _maybe_record(path, text)
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(text) == golden, (
        f"structure diverged from golden {name} "
        "(re-record intentionally with GOLDEN_UPDATE=1)"
    )
