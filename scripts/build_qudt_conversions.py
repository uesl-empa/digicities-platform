# SPDX-License-Identifier: Apache-2.0
"""Derive data/ontology/imports/qudt_conversions.json from a QUDT units vocabulary.

    python scripts/build_qudt_conversions.py <VOCAB_QUDT-UNITS-ALL.ttl> <release tag>

For each unit: its multiplier and offset to the SI unit of its dimension
(SI value = value * multiplier + offset) and its dimension vector. Two units
convert into each other only when their dimension vectors are the same.
The vocabulary is at https://github.com/qudt/qudt-public-repo,
src/main/rdf/vocab/unit/VOCAB_QUDT-UNITS-ALL.ttl at the release tag.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import rdflib

QUDT = rdflib.Namespace("http://qudt.org/schema/qudt/")
UNIT_NS = "http://qudt.org/vocab/unit/"
OUT = Path(__file__).resolve().parents[1] / "data" / "ontology" / "imports" / "qudt_conversions.json"


def build(ttl: Path, release: str) -> dict:
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    units = {}
    for unit in sorted(set(g.subjects(rdflib.RDF.type, QUDT.Unit)), key=str):
        if not str(unit).startswith(UNIT_NS):
            continue
        mult = g.value(unit, QUDT.conversionMultiplier) or g.value(unit, QUDT.conversionMultiplierSN)
        dim = g.value(unit, QUDT.hasDimensionVector)
        if mult is None or dim is None:
            continue
        offset = g.value(unit, QUDT.conversionOffset)
        units[str(unit)[len(UNIT_NS):]] = [float(mult), float(offset) if offset is not None else 0.0,
                                           str(dim).rsplit("/", 1)[-1]]
    return {"source": f"QUDT {release}, src/main/rdf/vocab/unit/VOCAB_QUDT-UNITS-ALL.ttl",
            "license": "CC BY 4.0, QUDT Project",
            "columns": ["multiplier", "offset", "dimension vector"],
            "units": units}


if __name__ == "__main__":
    data = build(Path(sys.argv[1]), sys.argv[2])
    OUT.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(len(data["units"]), "units ->", OUT)
