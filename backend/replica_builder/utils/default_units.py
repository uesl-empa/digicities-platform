# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Build the ``{attribute-class -> QUDT unit code}`` map from the ontology.

Used by the replica builder to *stamp* a default ``qudt:unit`` onto instances
whose workbook cell left the unit blank — so instances stay self-describing and
constrained to the ontology, rather than relying on a silent read-time fallback.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import rdflib
from rdflib import Namespace, URIRef

DICI = Namespace("https://digicities.info/ontology#")
_QUDT_UNIT_NS = "http://qudt.org/vocab/unit/"


def build_default_unit_map(graphs) -> Dict[str, str]:
    """Return ``{ClassLocalName: qudt_code}`` for every attribute class that
    declares a single ``dici_onto:hasDefaultUnit`` pointing at a QUDT unit IRI.

    Curve/ratio composite units (declared via a blank node) are skipped — there
    is no single ``qudt:unit`` code to stamp for those.
    """
    out: Dict[str, str] = {}
    for g in graphs:
        for cls, unit in g.subject_objects(DICI.hasDefaultUnit):
            if isinstance(unit, URIRef) and str(unit).startswith(_QUDT_UNIT_NS):
                out[str(cls).split("#")[-1]] = str(unit).rstrip("/").split("/")[-1]
    return out


def load_workspace_default_units(storage=None,
                                 ontology_dir: Optional[str] = None) -> Dict[str, str]:
    """Load the workspace's core + extension ontologies through the ontology-manager
    backend and build the default-unit map.

    Pass ``storage=ctx.storage`` from the UI, or ``ontology_dir`` for headless
    callers. Returns an empty map (safe no-op for stamping) if nothing loads.
    """
    try:
        from backend.ontology_manager.functions import create_ontology_functions
        of = create_ontology_functions(storage=storage, ontology_dir=ontology_dir)
    except Exception as e:  # pragma: no cover - defensive
        print(f"[replica-builder] could not open ontology for default units: {e}")
        return {}

    graphs: List[rdflib.Graph] = []
    try:
        graphs.append(of.load_core_ontology())
    except Exception:
        pass
    try:
        for ext in of.list_extension_files():
            try:
                graphs.append(of.load_extension(ext))
            except Exception:
                pass
    except Exception:
        pass
    return build_default_unit_map(graphs)


__all__ = ["build_default_unit_map", "load_workspace_default_units"]
