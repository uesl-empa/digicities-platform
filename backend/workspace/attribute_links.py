# SPDX-License-Identifier: Apache-2.0

"""Every attribute link a workspace's data uses is declared in its ontology.

The Ontology Manager and the Excel route only write links the ontology declares.
Other routes can still write one it does not: a hand-built file, a workspace
from before the scaffold, or a scenario whose class has no declared link yet.
A link that nothing declares is not an attribute link to any reader that asks
the ontology, so it is declared here, in the workspace's extension, the first
time the workspace is loaded.

    python -m backend.workspace.attribute_links <workspace folder>...

declares them for folders on disk, without a triplestore.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from rdflib import Graph
from rdflib.graph import ReadOnlyGraphAggregate

from backend.ontology_kinds import DICI, core_graph
from backend.ontology_scaffold import declare_used_links, local_name, undeclared_links

EXTENSIONS = "ontology/extensions"


def _target_extension(storage, workspace_id: Optional[str]) -> str:
    """The extension that takes the declarations: the workspace's largest, or a
    new one named after the workspace when it has none."""
    best, size = None, -1
    for rel in sorted(storage.glob(f"{EXTENSIONS}/*.ttl")):
        length = len(Graph().parse(data=storage.read_text(rel), format="turtle"))
        if length > size:
            best, size = rel, length
    return best or f"{EXTENSIONS}/{workspace_id or 'workspace'}_extension.ttl"


def declare_attribute_links(storage, schema: Graph, data: Graph,
                            workspace_id: Optional[str] = None) -> List[str]:
    """Declare what ``data`` uses and ``schema`` (core plus extensions) lacks,
    in the file and in ``schema``, and return the local names declared. If the
    file cannot be written the graph still gets them and the reason is printed.
    A workspace still loads whatever goes wrong here."""
    try:
        if not undeclared_links(schema, data):
            return []
        target = _target_extension(storage, workspace_id)
        write = Graph()
        if storage.exists(target):
            write.parse(data=storage.read_text(target), format="turtle")
        return _declare_into(storage, schema, data, workspace_id, target, write)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"[attribute_links] {workspace_id}: nothing declared: {exc}")
        return []


def _declare_into(storage, schema: Graph, data: Graph, workspace_id: Optional[str],
                  target: str, write: Graph) -> List[str]:
    before = set(write)
    view = ReadOnlyGraphAggregate([write, schema])
    declared, skipped = declare_used_links(view, write, data)
    for reason in skipped:
        print(f"[attribute_links] {workspace_id}: not declared: {reason}")
    if not declared:
        return []
    after = set(write)
    for triple in before - after:
        schema.remove(triple)
    schema += write
    names = [local_name(p) for p in declared]
    try:
        storage.write_text(target, _updated_text(storage, target, write, before, after))
        print(f"[attribute_links] {workspace_id}: declared {len(names)} in {target}")
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"[attribute_links] {workspace_id}: declared {len(names)} for this load only, "
              f"{target} could not be written: {exc}")
    return names


def _updated_text(storage, target: str, write: Graph, before: set, after: set) -> str:
    """The extension's new text: what was added goes at the end, so what is
    already written stays as it is, comments included. Only a change to a stated
    triple (a category moved under its parent's) rewrites the file."""
    write.bind("dici_onto", DICI)
    if before - after or not before:
        return write.serialize(format="turtle")
    added = Graph()
    added.bind("dici_onto", DICI)
    for triple in after - before:
        added.add(triple)
    return storage.read_text(target).rstrip() + "\n\n" + added.serialize(format="turtle")


def declare_in_folder(folder: str) -> List[str]:
    """:func:`declare_attribute_links` for a workspace folder on disk."""
    from backend.workspace.storage import WorkspaceStorage

    storage = WorkspaceStorage.local(folder)
    schema = core_graph() + Graph()
    for rel in storage.glob(f"{EXTENSIONS}/*.ttl"):
        schema.parse(data=storage.read_text(rel), format="turtle")
    data = Graph()
    for pattern in ("ingestion/output/*.ttl", "scenarios/*.ttl"):
        for rel in storage.glob(pattern):
            data.parse(data=storage.read_text(rel), format="turtle")
    return declare_attribute_links(storage, schema, data, Path(folder).name)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(path, declare_in_folder(path))
