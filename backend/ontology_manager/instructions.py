# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Replay a declarative extension-instruction file through the Ontology Manager.

The onboarding agent projects a confirmed spec onto an *instruction file*
(``ontology/extensions/<ws>_extension_instructions.json``) — a list of ontology
edits: component classes with parents, attribute classes with types/units,
attribute→component links, categorical named individuals, object properties,
reference classes and custom units.

``apply_extension_instructions`` executes that list against the workspace's
extension TTL by driving the SAME ``OntologyFunctions`` the Ontology Manager UI
uses (``add_component`` / ``add_attribute`` / ``link_attribute`` /
``add_named_individual``). The few op kinds the UI has no dedicated method for
(object properties, plain reference classes, custom units, SKOS annotations) are
written straight onto the extension graph and then merged into
``ontology/temp`` + ``ontology/exports`` by the same ``update_temp_and_export``
path — so the resulting extension TTL, the merged core+extension export and the
subsequent GraphDB load come out exactly as if the extension had been built by
hand in the UI.

Replay is idempotent: re-running the same instructions adds triples that already
exist (rdflib deduplicates), so a workspace can be re-onboarded safely.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import rdflib
from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .functions import OntologyFunctions
from .functions.base import dici_onto

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
PROV = Namespace("http://www.w3.org/ns/prov#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
QUDT_UNIT = "http://qudt.org/vocab/unit/"


def _uri(name: str) -> URIRef:
    """Resolve an instruction reference to a URI. A ``prefix:local`` value uses a
    known namespace (prov); a bare local name is in the dici_onto namespace."""
    if ":" in name and not name.startswith("http"):
        prefix, local = name.split(":", 1)
        if prefix == "prov":
            return PROV[local]
        if prefix in ("dici_onto", "dici"):
            return dici_onto[local]
    return dici_onto[name]


def _annotate(graph: rdflib.Graph, subject: URIRef, ann: Optional[dict]) -> None:
    """Attach the annotation triples an instruction carries (label/comment/
    alt_labels/scope_note) — the same fields the Ontology Manager forms expose."""
    if not ann:
        return
    if ann.get("label"):
        graph.set((subject, RDFS.label, Literal(ann["label"])))
    if ann.get("comment"):
        graph.add((subject, RDFS.comment, Literal(ann["comment"])))
    for alt in ann.get("alt_labels", []) or []:
        graph.add((subject, SKOS.altLabel, Literal(alt)))
    if ann.get("scope_note"):
        graph.add((subject, SKOS.scopeNote, Literal(ann["scope_note"])))


def apply_extension_instructions(
    instr: Dict[str, Any],
    ontology_dir: str,
    workspace_id: Optional[str] = None,
    graphdb_client=None,
) -> Dict[str, Any]:
    """Execute ``instr['instructions']`` against the workspace extension TTL.

    Args:
        instr: the parsed instruction file (``extension``, ``instructions``, …).
        ontology_dir: the workspace's ``.../ontology`` directory.
        workspace_id: workspace id (reporting / local-storage fallback).
        graphdb_client: optional UnifiedGraphDBClient (unused here; the load is
            done by ``ensure_workspace_repo`` after the build).

    Returns a report ``{extension, declared_classes, results}`` where ``results``
    is one ``{op, target, status, message}`` per instruction.
    """
    of = OntologyFunctions(
        ontology_dir=ontology_dir, workspace_id=workspace_id,
        graphdb_client=graphdb_client,
    )
    ext = instr.get("extension") or f"{workspace_id or 'extension'}.ttl"
    if ext not in of.list_extension_files():
        of.create_new_extension(ext)

    results: List[Dict[str, str]] = []
    declared_classes: List[str] = []

    def _direct(fn) -> tuple[bool, str]:
        """Run a direct extension-graph edit (load → mutate → save), for the op
        kinds the Ontology Manager exposes no method for."""
        g = of.load_extension(ext)
        msg = fn(g) or "ok"
        return (of.save_extension(ext, g), msg)

    for op in instr.get("instructions", []):
        kind = op.get("op")
        target = op.get("name") or op.get("attribute") or op.get("code") or ""
        try:
            if kind == "add_component":
                ok, msg = of.add_component(ext, op["name"], op.get("parent") or "Component")
                if ok:
                    declared_classes.append(op["name"])
                    if op.get("annotations"):
                        _direct(lambda g: _annotate(g, dici_onto[op["name"]], op["annotations"]))

            elif kind == "add_attribute":
                parent = op.get("parent")
                ok, msg = of.add_attribute(
                    ext, op["type"], op["name"],
                    qudt_unit=op.get("qudt_unit", ""),
                    y_qudt_unit=op.get("y_qudt_unit", ""),
                    x_unit=op.get("x_unit", ""),
                    temporal_precision=op.get("temporal_precision", ""),
                    parent_property=str(_uri(parent)) if parent else "",
                )
                if ok and op.get("annotations"):
                    _direct(lambda g: _annotate(g, dici_onto[op["name"]], op["annotations"]))

            elif kind == "link_attribute":
                ok, msg = of.link_attribute(
                    ext, str(dici_onto[op["component"]]), str(dici_onto[op["attribute"]]))
                target = f"{op.get('component')}·{op.get('attribute')}"

            elif kind == "add_named_individual":
                ok, msg = of.add_named_individual(
                    ext, op["name"], str(dici_onto[op["attribute"]]))
                if ok and op.get("annotations"):
                    _direct(lambda g: _annotate(g, dici_onto["".join(op["name"].split())], op["annotations"]))

            elif kind == "add_object_property":
                def _add_prop(g: rdflib.Graph) -> str:
                    uri = dici_onto[op["name"]]
                    g.add((uri, RDF.type, OWL.ObjectProperty))
                    if op.get("parent"):
                        g.add((uri, RDFS.subPropertyOf, _uri(op["parent"])))
                    if op.get("domain"):
                        g.add((uri, RDFS.domain, dici_onto[op["domain"]]))
                    if op.get("range"):
                        g.add((uri, RDFS.range, dici_onto[op["range"]]))
                    if op.get("inverse"):
                        g.add((uri, OWL.inverseOf, dici_onto[op["inverse"]]))
                    _annotate(g, uri, op.get("annotations"))
                    return "object property added"
                ok, msg = _direct(_add_prop)

            elif kind == "add_class":
                def _add_class(g: rdflib.Graph) -> str:
                    uri = dici_onto[op["name"]]
                    g.add((uri, RDF.type, OWL.Class))
                    # Reference kinds (the only add_class today) sit under Reference.
                    g.add((uri, RDFS.subClassOf, dici_onto["Reference"]))
                    g.add((uri, RDFS.label, Literal(op["name"])))
                    _annotate(g, uri, op.get("annotations"))
                    return "class added"
                ok, msg = _direct(_add_class)
                if ok:
                    declared_classes.append(op["name"])

            elif kind == "add_custom_unit":
                def _add_unit(g: rdflib.Graph) -> str:
                    uri = URIRef(QUDT_UNIT + op["code"])
                    g.add((uri, RDF.type, QUDT.Unit))
                    if op.get("label"):
                        g.add((uri, RDFS.label, Literal(op["label"])))
                    if op.get("comment"):
                        g.add((uri, RDFS.comment, Literal(op["comment"])))
                    return "custom unit added"
                ok, msg = _direct(_add_unit)

            else:
                ok, msg = False, f"unknown op '{kind}'"
        except Exception as exc:  # keep going; report the failure per-op
            ok, msg = False, f"{type(exc).__name__}: {exc}"

        results.append({"op": kind or "", "target": target,
                        "status": "ok" if ok else "error", "message": msg})

    # Consolidate the merged core+extension temp/export once at the end (the OM
    # ops already do this per call, but direct edits above skip it).
    of.update_temp_and_export(ext)

    return {"extension": ext, "declared_classes": declared_classes, "results": results}
