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
``change_parent``    :meth:`ComponentMixin.change_component_parent`
                     (``{"name", "parent"}``)
``rename_component`` :meth:`ComponentMixin.rename_component`
                     (``{"name", "new_name"}``)
``remove_component`` :meth:`ComponentMixin.remove_component` (``{"name"}``)
``annotate``         set annotations on an existing term (``{"name",
                     "annotations"}``)
===================  =====================================================

Checks, in the proper sequence, before anything is written (the same rules the
Ontology Manager UI applies — :mod:`.naming`, :mod:`.hierarchy`):

* a new class's name is a valid class name (PascalCase, not ``…Attribute``,
  at most 31 characters) and does not redefine a core term — a core class or
  attribute is REUSED (the op is skipped, never redeclared);
* a parent is an existing class: core, this extension, or declared earlier in
  the same file (so a hierarchy is written top-down in one file);
* a re-parent never puts a class under itself or its own subclass.

A refused op is reported as ``error`` with the reason; the replay continues.
:func:`check_extension_instructions` runs the same checks without writing
anything — a dry run to show the user before applying.

``annotations`` keys: ``label``, ``comment``, ``alt_labels``, ``scope_note``,
``definition`` (``skos:definition``), ``examples`` (``skos:example``).

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

from . import hierarchy
from .functions import create_ontology_functions, OntologyFunctions
from .naming import check_class_name, check_property_name

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


class _Checker:
    """The proper sequence, checked op by op against core + the extension as it
    stands AT THAT POINT of the file (classes declared earlier in the same file
    count). Shared by the replay (before each write) and the dry run (instead of
    writing). ``check`` returns ``("ok"|"skip"|"error", message)``; ``apply``
    records an op's structural effect (class, parent, rename, removal)."""

    def __init__(self, core: rdflib.Graph, ext: rdflib.Graph):
        self.core = core
        self.core_classes = hierarchy.classes(core)
        self.core_props = {n for n in (str(s)[len(str(dici_onto)):]
                                       for s in core.subjects(RDF.type, OWL.ObjectProperty)
                                       if str(s).startswith(str(dici_onto)))}
        self.ext_classes = hierarchy.classes(ext)
        self.ext_props = {str(s)[len(str(dici_onto)):]
                          for s in ext.subjects(RDF.type, OWL.ObjectProperty)
                          if str(s).startswith(str(dici_onto))}
        self.parents: Dict[str, List[str]] = {
            c: hierarchy.parents(ext, c) for c in self.ext_classes}

    # -- the tree as it stands ------------------------------------------------
    def known(self, name: str) -> bool:
        return name in self.core_classes or name in self.ext_classes

    def _parents_of(self, name: str) -> List[str]:
        if name in self.parents:
            return self.parents[name]
        return hierarchy.parents(self.core, name)

    def ancestors(self, name: str) -> List[str]:
        seen: List[str] = []
        frontier = self._parents_of(name)
        while frontier:
            nxt = []
            for p in frontier:
                if p not in seen and p != name:
                    seen.append(p)
                    nxt += self._parents_of(p)
            frontier = nxt
        return seen

    def _subclasses(self, name: str) -> List[str]:
        return sorted(c for c, ps in self.parents.items()
                      if name in ps and not c.endswith("Attribute"))

    @staticmethod
    def _local(term: str) -> str:
        return str(term).split("#")[-1].split(":")[-1]

    # -- per-op checks ----------------------------------------------------------
    def check(self, op: Dict[str, Any]):
        kind = op.get("op")
        name = op.get("name") or ""
        if kind in ("add_component", "add_class"):
            if name in self.core_classes:
                return "skip", f"`{name}` is a core class — used as it is, not redeclared"
            if name in self.ext_classes:
                return "skip", "class already in extension"
            chk = check_class_name(name, core=self.core, existing=self.ext_classes)
            if not chk.ok:
                return "error", "; ".join(chk.errors)
            parent = op.get("parent") or ("Component" if kind == "add_component" else "")
            if parent and not self.known(self._local(parent)):
                return "error", (f"parent `{self._local(parent)}` is not a class in the core "
                                 "ontology or this extension — declare it first")
            return "ok", "; ".join(chk.warnings)
        if kind == "add_attribute":
            if name in self.core_classes:
                return "skip", f"`{name}` is a core attribute — reused, not redeclared"
            if name in self.ext_classes:
                return "ok", ""                      # the executor reconciles its unit
            chk = check_class_name(name, core=self.core, existing=self.ext_classes)
            return ("ok", "; ".join(chk.warnings)) if chk.ok else ("error", "; ".join(chk.errors))
        if kind == "link_attribute":
            missing = [t for t in (op.get("component"), op.get("attribute"))
                       if not t or not self.known(self._local(t))]
            if missing:
                return "error", ("not a class in the core ontology or this extension: "
                                 + ", ".join(f"`{self._local(m or '')}`" for m in missing))
            return "ok", ""
        if kind == "add_named_individual":
            att = self._local(op.get("attribute") or "")
            if not self.known(att):
                return "error", f"attribute `{att}` is not declared"
            return "ok", ""
        if kind == "add_object_property":
            if name in self.core_props:
                return "skip", f"`{name}` is a core property — reused, not redeclared"
            if name in self.ext_props:
                return "skip", "property already in extension"
            chk = check_property_name(name)
            if not chk.ok:
                return "error", "; ".join(chk.errors)
            for end in ("domain", "range"):
                t = op.get(end)
                if t and ":" not in str(t).split("#")[-1] and not self.known(self._local(t)):
                    return "error", f"{end} `{self._local(t)}` is not a class — declare it first"
            return "ok", ""
        if kind == "change_parent":
            parent = self._local(op.get("parent") or "")
            if name not in self.ext_classes:
                return "error", (f"`{name}` is not a class of this extension"
                                 + (" (it is a core class)" if name in self.core_classes else ""))
            if not self.known(parent):
                return "error", f"parent `{parent}` is not a class — declare it first"
            if parent in self._parents_of(name):
                return "skip", f"`{name}` is already under `{parent}`"
            if parent == name or name in self.ancestors(parent):
                return "error", (f"`{parent}` is `{name}` itself or sits under it — a class "
                                 "can't be moved under its own subclass")
            return "ok", ""
        if kind == "rename_component":
            new = op.get("new_name") or ""
            if name not in self.ext_classes:
                if new in self.ext_classes:
                    return "skip", f"already renamed to `{new}`"
                return "error", f"`{name}` is not a class of this extension"
            chk = check_class_name(new, core=self.core, existing=self.ext_classes)
            return ("ok", "") if chk.ok else ("error", "; ".join(chk.errors))
        if kind == "remove_component":
            if name not in self.ext_classes:
                return "skip", f"`{name}` is not in this extension"
            subs = self._subclasses(name)
            if subs:
                return "error", (", ".join(f"`{s}`" for s in subs) + " sit under it — move or "
                                 "remove them first")
            return "ok", ""
        if kind == "annotate":
            if not (self.known(name) or name in self.ext_props or name in self.core_props):
                return "error", f"`{name}` is not a term of the core ontology or this extension"
            return "ok", ""
        return "ok", ""

    def apply(self, op: Dict[str, Any]) -> None:
        kind, name = op.get("op"), op.get("name") or ""
        if kind in ("add_component", "add_class", "add_attribute"):
            self.ext_classes.add(name)
            parent = op.get("parent") or ("Component" if kind == "add_component" else "")
            self.parents.setdefault(name, [self._local(parent)] if parent else [])
        elif kind == "add_object_property":
            self.ext_props.add(name)
        elif kind == "change_parent":
            self.parents[name] = [self._local(op["parent"])]
        elif kind == "rename_component":
            new = op["new_name"]
            self.ext_classes.discard(name)
            self.ext_classes.add(new)
            self.parents[new] = self.parents.pop(name, [])
            for c, ps in self.parents.items():
                self.parents[c] = [new if p == name else p for p in ps]
        elif kind == "remove_component":
            self.ext_classes.discard(name)
            self.parents.pop(name, None)


class _Executor:
    def __init__(self, funcs: OntologyFunctions, extension: str):
        self.funcs = funcs
        self.ext = extension
        self.results: List[Dict[str, str]] = []
        self.declared: List[str] = []
        self.checker = _Checker(funcs.load_core_ontology(), self._graph())

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

    def run(self, op: Dict[str, Any]) -> None:
        """Check the op against the tree as it stands, then execute it."""
        status, msg = self.checker.check(op)
        if status == "error":
            self._record(op, "error", msg)
            return
        if status == "skip":
            self._record(op, "skipped", msg)
            return
        n = len(self.results)
        getattr(self, op["op"])(op)
        if self.results[n:] and self.results[n]["status"] == "applied":
            self.checker.apply(op)
            if msg and not self.results[n]["message"]:
                self.results[n]["message"] = msg

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
        if ann.get("definition"):
            for old in list(g.objects(uri, SKOS.definition)):
                g.remove((uri, SKOS.definition, old))
            g.add((uri, SKOS.definition, Literal(ann["definition"], lang="en")))
        for ex in ann.get("examples") or []:
            if ex:
                g.add((uri, SKOS.example, Literal(ex, lang="en")))
        self._save(g)

    # -- ops -----------------------------------------------------------------

    def add_component(self, op: Dict[str, Any]) -> None:
        name = op["name"]
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

    def change_parent(self, op: Dict[str, Any]) -> None:
        ok, msg = self.funcs.change_component_parent(
            self.ext, str(_uri(op["name"])), str(_uri(op["parent"])))
        self._record(op, "applied" if ok else "error", msg)

    def rename_component(self, op: Dict[str, Any]) -> None:
        ok, msg = self.funcs.rename_component(
            self.ext, str(_uri(op["name"])), _label_for(op["new_name"]))
        if ok:
            self.declared = [op["new_name"] if d == op["name"] else d for d in self.declared]
        self._record(op, "applied" if ok else "error", msg)

    def remove_component(self, op: Dict[str, Any]) -> None:
        ok, msg = self.funcs.remove_component(self.ext, str(_uri(op["name"])))
        self._record(op, "applied" if ok else "error", msg)

    def annotate(self, op: Dict[str, Any]) -> None:
        self._annotate(op["name"], op.get("annotations"))
        self._record(op, "applied")


_OPS = ("add_component", "add_attribute", "link_attribute", "add_named_individual",
        "add_object_property", "add_class", "add_custom_unit", "change_parent",
        "rename_component", "remove_component", "annotate")


def check_extension_instructions(
    instructions: Union[Dict[str, Any], str, Path],
    storage=None,
    workspace_id: Optional[str] = None,
    ontology_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Dry run: the same checks :func:`apply_extension_instructions` makes before
    each write, op by op against core + the extension as it would stand at that
    point — nothing is written. ``{"ok", "results": [{op, target, status:
    ok|skipped|error, message}], "tree_classes"}`` so a caller can show the user
    what would happen (and why anything would be refused) before applying."""
    if isinstance(instructions, (str, Path)):
        instructions = json.loads(Path(instructions).read_text(encoding="utf-8"))
    ext = instructions.get("extension") or ""
    if ext and not ext.endswith(".ttl"):
        ext += ".ttl"
    funcs = create_ontology_functions(storage=storage,
                                      workspace_id=workspace_id or instructions.get("workspace"),
                                      ontology_dir=ontology_dir)
    ext_graph = (funcs.load_extension(ext)
                 if ext and funcs.storage.exists(f"{funcs.EXTENSION_PATH}/{ext}")
                 else rdflib.Graph())
    chk = _Checker(funcs.load_core_ontology(), ext_graph)
    results = []
    for op in instructions.get("instructions", []):
        kind = op.get("op")
        target = op.get("name") or op.get("code") \
            or f"{op.get('component', '')}→{op.get('attribute', '')}"
        if kind not in _OPS:
            results.append({"op": kind, "target": target, "status": "error",
                            "message": f"unknown op '{kind}'"})
            continue
        status, msg = chk.check(op)
        if status == "ok":
            chk.apply(op)
        results.append({"op": kind, "target": target,
                         "status": {"skip": "skipped"}.get(status, status), "message": msg})
    return {"ok": not any(r["status"] == "error" for r in results), "results": results,
            "parents": {c: ps for c, ps in chk.parents.items() if c in chk.ext_classes}}


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
            ex.run(op)
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
