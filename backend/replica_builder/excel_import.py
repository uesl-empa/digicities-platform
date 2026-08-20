# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Excel workbook → TTL → in-app instances, with ONE parser.

``components/replica_builder/replica_excel_importer.py`` used to carry a second,
independent workbook parser (``parse_excel_file``, ~300 LOC) that re-read the
sheets just to populate the session editor — drifting from the authoritative
converter (``process_excel_to_ttl``). This module replaces it: the converter
parses the workbook (single source of truth, including the ClassObject
link-target guard and default-unit stamping), and the session model is read
back out of the *generated TTL* via
:func:`backend.replica_builder.graph_loader.parse_local_replica_graph`.

So what the editor shows after an import is exactly what the TTL says — not a
parallel interpretation of the spreadsheet.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Graph

from backend.replica_builder.graph_loader import parse_local_replica_graph
from backend.replica_builder.model import ComponentInstance
from backend.replica_builder.utils.create_class_and_attribute_graph import process_excel_to_ttl


def import_workbook(
    xlsx_path: str,
    project_uri: str,
    uri_mode: str = "default",
    default_units: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[ComponentInstance]]:
    """Convert a digital-replica workbook to TTL and parse the model back.

    Returns ``(ttl_content, instances)``. Raises on conversion errors (the
    UI shim turns that into an error message).
    """
    fd, ttl_path = tempfile.mkstemp(suffix=".ttl")
    os.close(fd)
    try:
        process_excel_to_ttl(
            project_uri=project_uri,
            file_path=xlsx_path,
            output_ttl_path=ttl_path,
            uri_mode=uri_mode,
            default_units=default_units,
        )
        with open(ttl_path, "r", encoding="utf-8") as f:
            ttl_content = f.read()
    finally:
        try:
            os.unlink(ttl_path)
        except OSError:
            pass

    instances = parse_generated_ttl(ttl_content, project_uri=project_uri)
    return ttl_content, instances


def parse_generated_ttl(ttl_content: str,
                        project_uri: Optional[str] = None) -> List[ComponentInstance]:
    """Parse a generated classes_and_attributes TTL string into instances."""
    graph = Graph()
    graph.parse(data=ttl_content, format="turtle")
    return parse_local_replica_graph(graph, project_uri=project_uri)


def instances_payload(instances: List[ComponentInstance]) -> Dict[str, List[Dict[str, Any]]]:
    """The ``{'instances': [...]}`` dict shape the Streamlit import tab stores
    in session state (each entry has id / component_type / uri / label /
    attributes / annotations / class_objects)."""
    return {"instances": [inst.to_dict() for inst in instances]}


__all__ = ["import_workbook", "parse_generated_ttl", "instances_payload"]
