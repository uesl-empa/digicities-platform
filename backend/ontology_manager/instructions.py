# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Replay an extension-instruction file through the Ontology Manager backend.

An extension-instruction file is a declarative list of ontology edits — new
component classes, attribute classes with their types and units, attribute→
component links, named individuals, object properties — stored next to the
extension it builds (``ontology/extensions/<name>_extension_instructions.json``).
Agents (or scripts) AUTHOR the instruction file; this module EXECUTES it by
calling the same ``OntologyFunctions`` methods the Ontology Manager UI calls,
so the resulting extension TTL, the merged ``temp``/``exports`` files and the
GraphDB upload are byte-for-byte the artifacts a user would have produced by
clicking through the Ontology Manager.

Instruction file shape::

    {
      "version": 1,
      "workspace": "my-workspace",
      "extension": "my-workspace.ttl",          # file under ontology/extensions/
      "generated_by": "onboarding-agent",
      "instructions": [
        {"op": "add_component", "name": "WindPark", "parent": "Location",
         "annotations": {"comment": "...", "alt_labels": ["Wind Farm"],
                         "scope_note": "..."}},
        {"op": "add_attribute", "name": "HubHeight", "type": "Physical",
         "qudt_unit": "M"},
        {"op": "add_attribute", "name": "PowerCurve", "type": "Curve",
         "qudt_unit": "M-PER-SEC", "y_qudt_unit": "KiloW"},
        {"op": "add_attribute", "name": "SiteType", "type": "Categorical"},
        {"op": "add_named_individual", "name": "GlobalWindAtlasSite",
         "attribute": "SiteType",
         "annotations": {"label": "Site referenced in Global Wind Atlas"}},
        {"op": "link_attribute", "component": "WindTurbine",
         "attribute": "HubHeight"},
        {"op": "add_object_property", "name": "partOfWindpark",
         "parent": "linksComponent", "domain": "WindTurbine",
         "range": "WindPark", "inverse": "hasTurbine"},
        {"op": "add_class", "name": "OnboardedFile",
         "annotations": {"comment": "Kind of cited source."}},
        {"op": "add_custom_unit", "code": "VehiclePerHour",
         "label": "vehicles per hour"}
      ]
    }

Op → backend mapping:

===================  =====================================================
``add_component``    :meth:`ComponentMixin.add_component` (also builds the
                     ``<Class>Attribute`` hierarchy + ``has<Class>Attribute``
                     property, exactly like the UI)
``add_attribute``    :meth:`AttributeMixin.add_attribute`; ``type`` is one of
                     the Ontology Manager's type strings (``Physical``,
                     ``Simple Cost``, ``Unit-Based Cost``, ``Curve``,
                     ``Categorical``, ``Geospatial``, ``CustomPhysicalRatio``,
                     ``Event``, ``SimpleValue``); optional ``parent`` places it
                     under a different superclass (e.g. ``DynamicAttribute``)
``link_attribute``   :meth:`AttributeMixin.link_attribute`
``add_named_individual`` :meth:`AttributeMixin.add_named_individual`
``add_object_property``  no UI equivalent — written straight into the
                     extension graph through the same load→save→export flow
``add_class``        plain ``owl:Class`` (reference kinds etc.), same flow
``add_custom_unit``  ``unit:<code> a qudt:Unit``, same flow
===================  =====================================================

Names and labels: the Ontology Manager derives a class name by stripping the
whitespace from its label. Instructions carry the ``name``; the label passed to
the backend is its humanized form (``HubHeight`` → ``"Hub Height"``), which
round-trips to the same name. A different display label can be set with
``annotations.label`` — applied after creation, replacing ``rdfs:label``.

Replays are idempotent: an instruction whose target already exists in the
extension is skipped (so a file can be appended to and re-run), except that a
changed default unit on an existing attribute is reconciled through
:meth:`AttributeMixin.set_default_unit`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import rdflib
from rdflib import Literal, Namespace, OWL, RDF, RDFS, URIRef

from .functions import create_ontology_functions, OntologyFunctions

dici_onto = Namespace("https://digicities.info/ontology#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
UNIT = Namespace("http://qudt.org/vocab/unit/")
PROV = Namespace("http://www.w3.org/ns/prov#")

# Prefixes an instruction may use for non-dici terms (e.g. "prov:wasDerivedFrom").
_PREFIXES = {
    "prov": PROV, "skos": SKOS, "qudt": QUDT, "unit": UNIT,
    "owl": OWL, "rdfs": RDFS, "dici_onto": dici_onto,
}


def _uri(term: str) -> URIRef:
    """Resolve an instruction term: full IRI, ``prefix:name``, or dici local name."""
    if term.startswith(("http://", "https://")):
        return URIRef(term)
    if ":" in term:
        prefix, local = term.split(":", 1)
        if prefix in _PREFIXES:
            return _PREFIXES[prefix][local]
    return dici_onto[term]


def _humanize(name: str) -> str:
    """PascalCase → spaced words (mirror of the OM label→name strip)."""
    import re
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s.strip()


def _label_for(name: str) -> str:
    """A label the OM will strip back to exactly ``name`` (falls back to the
    name itself when humanizing wouldn't round-trip, e.g. underscores)."""
    label = _humanize(name)
    return label if "".join(label.split()) == name else name


class _Executor:
    def __init__(self, funcs: OntologyFunctions, extension: str):
        self.funcs = funcs
        self.ext = extension
        self.results: List[Dict[str, str]] = []
        self.declared: List[str] = []

    # -- bookkeeping ---------------------------------------------------------

    def _record(self, op: Dict[str, Any], status: str, message: str = "") -> None:
        self.results.append({
            "op": op.get("op", "?"),
            "target": op.get("name") or op.get("code")
                      or f"{op.get('component', '')}→{op.get('attribute', '')}",
            "status": status, "message": message,
        })

    def _graph(self) -> rdflib.Graph:
        return self.funcs.load_extension(self.ext)

    def _class_exists(self, name: str) -> bool:
        return (dici_onto[name], RDF.type, OWL.Class) in self._graph()

    def _save(self, g: rdflib.Graph) -> None:
        """The same persist flow every OM mutation ends with."""
        self.funcs.save_extension(self.ext, g)
        self.funcs.update_temp_and_export(self.ext)

    # -- annotations ---------------------------------------------------------

    def _annotate(self, name: str, ann: Optional[Dict[str, Any]]) -> None:
        if not ann:
            return
        g = self._graph()
        uri = dici_onto[name]
        if ann.get("label"):
            for old in list(g.objects(uri, RDFS.label)):
                g.remove((uri, RDFS.label, old))
            g.add((uri, RDFS.label, Literal(ann["label"])))
        if ann.get("comment"):
            g.add((uri, RDFS.comment, Literal(ann["comment"], lang="en")))
        for alt in ann.get("alt_labels") or []:
            if alt:
                g.add((uri, SKOS.altLabel, Literal(alt, lang="en")))
        if ann.get("scope_note"):
            g.add((uri, SKOS.scopeNote, Literal(ann["scope_note"], lang="en")))
        self._save(g)

    # -- ops -----------------------------------------------------------------

    def add_component(self, op: Dict[str, Any]) -> None:
        name = op["name"]
        if self._class_exists(name):
            self._record(op, "skipped", "class already in extension")
            return
        ok, msg = self.funcs.add_component(self.ext, _label_for(name),
                                           op.get("parent") or "Component")
        if ok:
            self.declared.append(name)
            self._annotate(name, op.get("annotations"))
        self._record(op, "applied" if ok else "error", msg)

    def add_attribute(self, op: Dict[str, Any]) -> None:
        name = op["name"]
        if self._class_exists(name):
            # Reconcile a changed simple default unit; everything else is append-only.
            unit = op.get("qudt_unit")
            if unit and op.get("type") in ("Physical", "Geospatial"):
                current = set(self._graph().objects(dici_onto[name], dici_onto.hasDefaultUnit))
                if current and UNIT[unit] not in current:
                    ok, msg = self.funcs.set_default_unit(self.ext, name, unit)
                    self._record(op, "applied" if ok else "skipped",
                                 msg if ok else f"unit not reconciled: {msg}")
                    return
            self._record(op, "skipped", "attribute already in extension")
            return
        ok, msg = self.funcs.add_attribute(
            self.ext,
            attribute_type=op["type"],
            attribute_label=_label_for(name),
            qudt_unit=op.get("qudt_unit") or "",
            y_qudt_unit=op.get("y_qudt_unit") or "",
            x_unit=op.get("x_unit") or "",
            temporal_precision=op.get("temporal_precision") or "",
            parent_property=op.get("parent") or "",
        )
        if ok:
            self.declared.append(name)
            self._annotate(name, op.get("annotations"))
        self._record(op, "applied" if ok else "error", msg)

    def link_attribute(self, op: Dict[str, Any]) -> None:
        component = str(_uri(op["component"]))
        attribute = str(_uri(op["attribute"]))
        ok, msg = self.funcs.link_attribute(self.ext, component, attribute)
        self._record(op, "applied" if ok else "error", msg)

    def add_named_individual(self, op: Dict[str, Any]) -> None:
        name = op["name"]
        if (dici_onto[name], RDF.type, OWL.NamedIndividual) in self._graph():
            self._record(op, "skipped", "individual already in extension")
            return
        ok, msg = self.funcs.add_named_individual(
            self.ext, _label_for(name), str(_uri(op["attribute"])))
        if ok:
            self._annotate(name, op.get("annotations"))
        self._record(op, "applied" if ok else "error", msg)

    def add_object_property(self, op: Dict[str, Any]) -> None:
        name = op["name"]
        uri = dici_onto[name]
        g = self._graph()
        if (uri, RDF.type, OWL.ObjectProperty) in g:
            self._record(op, "skipped", "property already in extension")
            return
        g.add((uri, RDF.type, OWL.ObjectProperty))
        g.add((uri, RDFS.label, Literal(op.get("label") or _label_for(name))))
        if op.get("parent"):
            g.add((uri, RDFS.subPropertyOf, _uri(op["parent"])))
        if op.get("domain"):
            g.add((uri, RDFS.domain, _uri(op["domain"])))
        if op.get("range"):
            g.add((uri, RDFS.range, _uri(op["range"])))
        if op.get("inverse"):
            g.add((uri, OWL.inverseOf, _uri(op["inverse"])))
        self._save(g)
        self._annotate(name, op.get("annotations"))
        self._record(op, "applied")

    def add_class(self, op: Dict[str, Any]) -> None:
        name = op["name"]
        if self._class_exists(name):
            self._record(op, "skipped", "class already in extension")
            return
        g = self._graph()
        uri = dici_onto[name]
        g.add((uri, RDF.type, OWL.Class))
        g.add((uri, RDFS.label, Literal(_label_for(name))))
        if op.get("parent"):
            g.add((uri, RDFS.subClassOf, _uri(op["parent"])))
        self._save(g)
        self.declared.append(name)
        self._annotate(name, op.get("annotations"))
        self._record(op, "applied")

    def add_custom_unit(self, op: Dict[str, Any]) -> None:
        code = op["code"]
        uri = UNIT[code]
        g = self._graph()
        if (uri, RDF.type, QUDT.Unit) in g:
            self._record(op, "skipped", "unit already in extension")
            return
        g.add((uri, RDF.type, QUDT.Unit))
        g.add((uri, RDFS.label, Literal(op.get("label") or code)))
        if op.get("comment"):
            g.add((uri, RDFS.comment, Literal(op["comment"], lang="en")))
        self._save(g)
        self._record(op, "applied")


_OPS = ("add_component", "add_attribute", "link_attribute", "add_named_individual",
        "add_object_property", "add_class", "add_custom_unit")


def apply_extension_instructions(
    instructions: Union[Dict[str, Any], str, Path],
    storage=None,
    workspace_id: Optional[str] = None,
    graphdb_client=None,
    ontology_dir: Optional[str] = None,
    upload: Optional[bool] = None,
) -> Dict[str, Any]:
    """Execute an instruction file: create/extend the extension through the
    Ontology Manager backend, refresh the merged core+extension ``temp``/
    ``exports`` files, and (when a GraphDB client is available) upload the
    export to the workspace's ontology named graph — the full Ontology Manager
    save flow, driven from a file instead of the UI.

    Args:
        instructions: the instruction dict, or a local path to its JSON file.
        storage / workspace_id / graphdb_client / ontology_dir: forwarded to
            :func:`create_ontology_functions` (same construction the UI uses).
        upload: force the GraphDB upload on/off. Default: upload exactly when a
            ``graphdb_client`` is provided. (Workspace provisioning —
            ``ensure_workspace_repo`` — re-reads ``ontology/extensions/*.ttl``
            and materializes the inference closure, so callers that provision
            right after can leave the client out.)

    Returns:
        Report dict: ``extension``, ``results`` (one entry per instruction),
        ``declared_classes``, ``export``, ``uploaded``, ``ok``.
    """
    if isinstance(instructions, (str, Path)):
        instructions = json.loads(Path(instructions).read_text(encoding="utf-8"))

    ext = instructions.get("extension")
    if not ext:
        raise ValueError("instruction file has no 'extension' filename")
    if not ext.endswith(".ttl"):
        ext += ".ttl"

    funcs = create_ontology_functions(
        storage=storage,
        workspace_id=workspace_id or instructions.get("workspace"),
        graphdb_client=graphdb_client,
        ontology_dir=ontology_dir,
    )

    if not funcs.storage.exists(f"{funcs.EXTENSION_PATH}/{ext}"):
        funcs.create_new_extension(ext)

    ex = _Executor(funcs, ext)
    for op in instructions.get("instructions", []):
        kind = op.get("op")
        if kind not in _OPS:
            ex._record(op, "error", f"unknown op '{kind}'")
            continue
        try:
            getattr(ex, kind)(op)
        except Exception as e:                       # keep replaying; report it
            ex._record(op, "error", str(e))

    export = funcs.update_temp_and_export(ext)

    uploaded = False
    if upload is None:
        upload = graphdb_client is not None
    if upload:
        if graphdb_client is None:
            ex.results.append({"op": "upload", "target": ext, "status": "error",
                               "message": "upload requested but no graphdb_client"})
        else:
            ok, info = funcs.upload_to_graphdb(ext)
            uploaded = ok
            ex.results.append({"op": "upload", "target": ext,
                               "status": "applied" if ok else "error",
                               "message": str(info.get("message") or info.get("error", ""))})

    errors = [r for r in ex.results if r["status"] == "error"]
    return {
        "extension": ext,
        "results": ex.results,
        "declared_classes": ex.declared,
        "export": export.get("export"),
        "uploaded": uploaded,
        "ok": not errors,
    }
