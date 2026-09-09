# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Storage-backend parity (phase 4): the same operations, the same answers.

Every ``WorkspaceStorage`` consumer (Ontology Manager, Replica Builder,
scenario sync, the mirror layer) is written against the protocol-agnostic op
surface — so the op surface itself must behave identically whatever filesystem
sits underneath. This suite runs one canonical workspace lifecycle over each
backend and diffs the observable results.

In-process backends only (always runs; ``local`` + a second fsspec filesystem
wearing a remote protocol label — the exact surface the WebDAV backend
exposes). The REAL NextCloud variant of the same checks lives in
``tests/test_nextcloud_live.py`` (``-m live``), used both before deployment
(local overlay) and after (cloud instance).
"""
from __future__ import annotations

import fsspec
import pytest

from backend.workspace.storage import WorkspaceStorage


def _local(tmp_path):
    return WorkspaceStorage.local(str(tmp_path / "local-ws"))


def _remoteish(tmp_path):
    root = tmp_path / "remote-ws"
    root.mkdir(parents=True, exist_ok=True)
    return WorkspaceStorage(fsspec.filesystem("file"),
                            str(root).replace("\\", "/"), "webdav")


@pytest.fixture(params=["local", "remoteish"])
def storage(request, tmp_path):
    return {"local": _local, "remoteish": _remoteish}[request.param](tmp_path)


def test_lifecycle_parity(storage):
    """write → read → glob → walk → overwrite → delete, byte-identical."""
    storage.mkdir("ingestion/output")
    storage.write_text("ingestion/output/ws.ttl", "@prefix : <urn:x> . :a :b :c .")
    storage.write_bytes("scenarios/baseline.ttl", "thin — scénario".encode("utf-8"))

    assert storage.exists("ingestion/output/ws.ttl")
    assert storage.isdir("ingestion/output")
    assert storage.read_text("ingestion/output/ws.ttl").startswith("@prefix")
    assert storage.read_bytes("scenarios/baseline.ttl").decode("utf-8") \
        == "thin — scénario"

    assert storage.glob("ingestion/output/*.ttl") == ["ingestion/output/ws.ttl"]
    walked = storage.walk_files()
    assert set(walked) == {"ingestion/output/ws.ttl", "scenarios/baseline.ttl"}
    assert walked["ingestion/output/ws.ttl"]["size"] > 0

    storage.write_text("ingestion/output/ws.ttl", "@prefix : <urn:x> . :a :b :NEW .")
    assert ":NEW" in storage.read_text("ingestion/output/ws.ttl")

    storage.delete("scenarios/baseline.ttl")
    assert not storage.exists("scenarios/baseline.ttl")
    assert set(storage.walk_files()) == {"ingestion/output/ws.ttl"}


def test_canonical_layout_parity(storage):
    created = storage.ensure_canonical_layout()
    assert isinstance(created, list)
    for d in ("ontology/extensions", "scenarios", "services"):
        assert storage.isdir(d), d


def test_missing_paths_answer_the_same_way(storage):
    assert storage.exists("nope/nothing.ttl") is False
    assert storage.glob("nope/*.ttl") == []
    assert storage.ls("nope") == []
    storage.delete("nope/nothing.ttl")          # deleting the absent: silent no-op
