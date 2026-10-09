# SPDX-License-Identifier: Apache-2.0

"""Guard: string matching is banned; the other known code debt may only go DOWN.

Four kinds of debt are found per file, from the AST:

- ``str_heuristic``  ontology meaning read from a name: ``"hasAttribute" in p``,
                     ``uri.endswith("Attribute")``, ``attr_type == "Curve"``,
                     ``str(uri).startswith(str(DICI))``, a SPARQL
                     ``CONTAINS(STR(?x), ...)``. BANNED: there must be none. Ask
                     the ontology instead (``rdfs:subPropertyOf*`` /
                     ``rdfs:subClassOf*``, ``backend.ontology_kinds``).
- ``except_broad``   ``except:``, ``except Exception``, ``except BaseException``
                     (also inside a tuple). They hide the real failure.
- ``except_silent``  a handler of any type whose body is only ``pass``,
                     ``continue``, ``...`` or a string. The error vanishes.
- ``fstring_turtle`` Turtle / N-Triples built in an f-string. Build an rdflib
                     Graph and serialize it.

The last three are ratcheted: ``tests/code_debt_baseline.json`` holds their
count per file. The test fails when a file goes ABOVE its count (new debt; a
file not in the baseline counts as 0) and when it goes BELOW (debt paid off, so
lock it in):

    python tests/test_code_debt_ratchet.py --tighten

``--tighten`` only lowers counts; it never raises one. A line that is not debt
(a false positive) is exempt with a trailing ``# debt-ok: <reason>`` comment on
the line the construct starts on. The reason is required.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [REPO / "backend", REPO / "apps"]
BASELINE = Path(__file__).resolve().parent / "code_debt_baseline.json"
KINDS = ("except_broad", "except_silent", "str_heuristic", "fstring_turtle")
# Kinds that must not occur at all, and kinds held at a count that only falls.
BANNED = ("str_heuristic",)
RATCHETED = tuple(k for k in KINDS if k not in BANNED)

DEBT_OK = re.compile(r"#\s*debt-ok:\s*\S")
# Ontology terms: the core's class and object-property local names, the
# attribute kind tags, and anything shaped like a predicate (hasX, linksX,
# partOf...) or ending in a class suffix. Comparing a string with one of these
# is a guess at meaning.
ONTO_TERM = re.compile(
    r"^(has|is|links|feeds|part|located|contains|derived|uses|based)[A-Z]\w*$"
    r"|^\w*(Attribute|Component|Property|Class)$")
# A SPARQL string test on an IRI: FILTER(CONTAINS(STR(?x), "Attribute")).
SPARQL_STR_TEST = re.compile(r"\b(CONTAINS|STRSTARTS|STRENDS|REGEX)\s*\(\s*STR\s*\(", re.I)


def _core_terms() -> frozenset:
    from rdflib import OWL, RDF
    from backend.ontology_kinds import DICI, AttributeKind, core_graph
    ns = str(DICI)
    names = {k.value for k in AttributeKind}
    for kind in (OWL.Class, OWL.ObjectProperty):
        names |= {str(s)[len(ns):] for s in core_graph().subjects(RDF.type, kind)
                  if str(s).startswith(ns)}
    return frozenset(names)


if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
CORE_TERMS = _core_terms()


# Turtle detection works on the literal text with every {interpolation}
# replaced by X. SPARQL is out of scope here.
SPARQL = re.compile(r"\?[A-Za-z_]|\b(SELECT|ASK|CONSTRUCT|INSERT|DELETE|WHERE|FILTER|OPTIONAL)\b")
TURTLE_TERM = re.compile(r"<X>|<https?://[^>\s]*>|\b[a-z][\w-]*:[A-Za-z]")
TURTLE_END = re.compile(r"\s[;.,]\s*$")
NTRIPLE = re.compile(r"^\s*X\s+X\s+\S+\s+\.\s*$")


def _is_broad(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in ("Exception", "BaseException")
    if isinstance(node, ast.Tuple):
        return any(_is_broad(e) for e in node.elts)
    return False


def _is_silent(body: list[ast.stmt]) -> bool:
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, (ast.Pass, ast.Continue)):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _is_turtle(node: ast.JoinedStr) -> bool:
    text = "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
    if SPARQL.search(text):
        return False
    if "@prefix" in text:
        return True
    return any(TURTLE_END.search(line) and (TURTLE_TERM.search(line) or NTRIPLE.match(line))
               for line in text.splitlines())


def _is_term(value) -> bool:
    return isinstance(value, str) and (value in CORE_TERMS or bool(ONTO_TERM.match(value.lstrip("#/"))))


def _onto_strings(node: ast.expr) -> bool:
    vals = node.elts if isinstance(node, (ast.Tuple, ast.List, ast.Set)) else [node]
    return any(isinstance(v, ast.Constant) and _is_term(v.value) for v in vals)


NAMESPACE_NAME = re.compile(r"^_?(dici(_onto)?|ns|\w*_ns|\w*namespace)$", re.I)


def _mentions_namespace(node: ast.expr) -> bool:
    """A namespace object (``DICI``, ``QUDT_NS``, ``str(DICI)``) or a prefix built
    by gluing a ``/`` or ``#`` onto an IRI (``uri + "/"``, ``f"{root}/"``)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and NAMESPACE_NAME.search(sub.id):
            return True
        if isinstance(sub, ast.Attribute) and NAMESPACE_NAME.search(sub.attr):
            return True
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Add) and any(
                isinstance(side, ast.Constant) and isinstance(side.value, str)
                and side.value.endswith(("/", "#")) for side in (sub.left, sub.right)):
            return True
        if isinstance(sub, ast.JoinedStr) and sub.values \
                and isinstance(sub.values[-1], ast.Constant) \
                and str(sub.values[-1].value).endswith(("/", "#")):
            return True
    return False


def _is_str_heuristic(node: ast.AST) -> bool:
    if isinstance(node, ast.Compare):
        if _onto_strings(node.left) or any(_onto_strings(c) for c in node.comparators):
            return True
        # `str(DICI) in uri`: a namespace prefix test on an IRI.
        # A triple pattern `(s, p, o) in graph` is a graph lookup, not text.
        return (any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
                and not isinstance(node.left, ast.Tuple)
                and _mentions_namespace(node.left))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return (node.func.attr in ("endswith", "startswith")
                and any(_onto_strings(a) or _mentions_namespace(a) for a in node.args))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(SPARQL_STR_TEST.search(node.value))
    return False


def scan_file(path: Path) -> dict[str, list[int]]:
    """Line numbers of each kind of debt in one file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    found: dict[str, list[int]] = defaultdict(list)
    for node in ast.walk(tree):
        kinds = []
        if isinstance(node, ast.ExceptHandler):
            if _is_broad(node.type):
                kinds.append("except_broad")
            if _is_silent(node.body):
                kinds.append("except_silent")
        if isinstance(node, ast.JoinedStr) and _is_turtle(node):
            kinds.append("fstring_turtle")
        if _is_str_heuristic(node):
            kinds.append("str_heuristic")
        if kinds and not DEBT_OK.search(lines[node.lineno - 1]):
            for kind in kinds:
                found[kind].append(node.lineno)
    return found


def scan() -> dict[str, dict[str, list[int]]]:
    """{kind: {repo-relative file: [line, ...]}} over every scanned file."""
    out: dict[str, dict[str, list[int]]] = {k: {} for k in KINDS}
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            for kind, hits in scan_file(path).items():
                out[kind][rel] = sorted(hits)
    return out


def _load_baseline() -> dict[str, dict[str, int]]:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {k: data.get(k, {}) for k in RATCHETED}


def _compare(current, baseline):
    """(new debt, paid-off debt) as readable lines."""
    worse, better = [], []
    for kind in RATCHETED:
        for rel in sorted(set(current[kind]) | set(baseline[kind])):
            now, was = len(current[kind].get(rel, [])), baseline[kind].get(rel, 0)
            if now > was:
                lines = ", ".join(map(str, current[kind][rel]))
                worse.append(f"{kind}  {rel}: {was} -> {now}  (lines {lines})")
            elif now < was:
                better.append(f"{kind}  {rel}: {was} -> {now}")
    return worse, better


def test_detectors_find_each_kind(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "try:\n"
        "    x = 1\n"
        "except Exception:\n"                                 # 3 broad + silent
        "    pass\n"
        "try:\n"
        "    x = 1\n"
        "except (KeyError, Exception):  # debt-ok: test\n"    # 7 exempt
        "    raise\n"
        "ok = 'hasAttribute' in p\n"                           # 9
        "ok = uri.endswith(('Attribute', '.ttl'))\n"           # 10
        "key = 'hasHistoricTimeSeries' in d  # debt-ok: dict key\n"
        "msg = f'Noted: {x}.'\n"                               # prose, not Turtle
        "q = f'SELECT ?s WHERE {{ <{u}> a ?t . }}'\n"          # SPARQL, not Turtle
        "t = f'<{u}> a dici_onto:Scenario ;'\n"                # 14
        "n = f'{s} {p} {o} .'\n"                               # 15
        "ok = str(t).startswith(str(DICI))\n"                  # 16
        "ok = s.startswith(component_uri + '/')\n"             # 17
        "ok = str(QUDT_NS) in u\n"                             # 18
        "ok = name.startswith('tmp_')\n"                       # not a namespace
        "ok = (s, RDF.type, DICI.Scenario) in g\n"             # a graph lookup
        "ok = namespace_session_key in state\n"                # not a namespace
        "ok = s.startswith(f'{root}/')\n",                     # 22
        encoding="utf-8")
    found = scan_file(sample)
    assert found["except_broad"] == [3]
    assert found["except_silent"] == [3]
    assert sorted(found["str_heuristic"]) == [9, 10, 16, 17, 18, 22]
    assert sorted(found["fstring_turtle"]) == [14, 15]


def test_no_string_matching_in_code():
    found = scan()["str_heuristic"]
    sites = [f"{rel}: lines {', '.join(map(str, lines))}" for rel, lines in sorted(found.items())]
    assert not sites, (
        "String matching is banned: what a class, predicate or attribute IS comes "
        "from the ontology (rdfs:subClassOf* / rdfs:subPropertyOf*, "
        "backend.ontology_kinds), never from its name. A line that is not ontology "
        "matching (a workbook sheet name, say) takes a `# debt-ok: <reason>` "
        "comment.\n" + "\n".join(sites))


def test_code_debt_does_not_grow():
    worse, _ = _compare(scan(), _load_baseline())
    assert not worse, (
        "New code debt. Narrow the exception and log or raise it; build Turtle with "
        "rdflib. A false positive takes a `# debt-ok: <reason>` comment on that "
        "line.\n" + "\n".join(worse))


def test_code_debt_baseline_is_tight():
    _, better = _compare(scan(), _load_baseline())
    assert not better, (
        "Debt went down. Lock it in with "
        "`python tests/test_code_debt_ratchet.py --tighten`:\n" + "\n".join(better))


def tighten() -> None:
    """Lower the baseline to the current counts. Never raises a count."""
    current = scan()
    baseline = _load_baseline() if BASELINE.exists() else None
    out = {}
    for kind in RATCHETED:
        counts = {rel: len(hits) for rel, hits in current[kind].items() if hits}
        if baseline is not None:
            counts = {rel: min(n, baseline[kind].get(rel, 0)) for rel, n in counts.items()}
            counts = {rel: n for rel, n in counts.items() if n}
        out[kind] = dict(sorted(counts.items()))
    BASELINE.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for kind in RATCHETED:
        print(f"{kind}: {sum(out[kind].values())}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--tighten"]:
        tighten()
    elif sys.argv[1:] == ["--init"] and not BASELINE.exists():
        tighten()
    else:
        sys.exit("usage: python tests/test_code_debt_ratchet.py --tighten")
