# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Results a service hands back as a link to a file.

An ``outputs`` block with ``file_field`` says the response holds a link rather than
the values. The link can stop being good: the service may overwrite the file on its
next run. So the platform fetches each file as soon as the call returns and keeps it
with the run, and states which component instance it belongs to and whether its
columns are the ones the contract declared.
"""
from __future__ import annotations

import csv
import re
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from backend.api_submission.connection import auth_headers, expand_env, resolve_connection
from backend.api_submission.transports import safe_get
from backend.service_requirements.contract import SCENARIO_CLASS, parse_outputs

MAX_FILE_BYTES = 200 * 1024 * 1024


def _read_field(node: Any, dotted: str) -> Any:
    """A response field. Fields of a nested result are written with dots."""
    for part in dotted.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _instance_of(block: Any, call: Dict[str, Any]) -> Any:
    """Which component the result belongs to: the block's ``identified_by``, from the
    response or else the request. Without one, the uri of the component this call asked
    about. A result of the whole run belongs to no component."""
    if block.component == SCENARIO_CLASS:
        return None
    request = call.get("request")
    if block.identified_by:
        return _read_field(call["response"], block.identified_by) or _read_field(request, block.identified_by)
    return _read_field(request, "uri")


def _answered_calls(response_data: Any, success: bool) -> List[Dict[str, Any]]:
    """Each call that returned: every good one of a GET, or the one response of a POST."""
    calls = response_data.get("calls") if isinstance(response_data, dict) else None
    if isinstance(calls, list):
        return [c for c in calls if not c.get("error")]
    return [{"response": response_data}] if success else []


def _download(url: str, conn: Dict[str, Any], timeout: int) -> bytes:
    """The file's bytes. The service's credentials go only to the service's own host,
    and are then not carried through a redirect to somewhere else."""
    import requests

    same_host = urlsplit(url)[:2] == urlsplit(conn.get("url", ""))[:2]
    headers, auth = auth_headers(conn) if same_host else ({}, None)
    with safe_get(url, headers=headers, auth=auth, timeout=timeout, stream=True,
                  allow_redirects=not (headers or auth)) as resp:
        if resp.status_code != 200:
            raise requests.exceptions.RequestException(f"status {resp.status_code}")
        data = bytearray()
        for chunk in resp.iter_content(1024 * 1024):
            data.extend(chunk)
            if len(data) > MAX_FILE_BYTES:
                raise requests.exceptions.RequestException(
                    f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    return bytes(data)


def _table_shape(data: bytes, url: str) -> Optional[Tuple[List[str], int]]:
    """(columns, rows) of a csv or tsv file. None for any other file."""
    if PurePosixPath(urlsplit(url).path).suffix.lower() not in (".csv", ".tsv"):
        return None
    lines = data.decode("utf-8-sig", errors="replace").splitlines()
    if not lines:
        return [], 0
    try:
        dialect: Any = csv.Sniffer().sniff(lines[0], delimiters=",;\t")
    except csv.Error:
        dialect = "excel"
    return next(csv.reader(lines[:1], dialect)), sum(1 for line in lines[1:] if line.strip())


def _fetch_one(source: str, number: int, conn: Dict[str, Any], timeout: int,
               save: Callable[[str, bytes], str]) -> Dict[str, Any]:
    import requests

    try:
        data = _download(source, conn, timeout)
    except requests.exceptions.RequestException as exc:
        return {"error": f"Could not fetch the result file: {exc}"}
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", PurePosixPath(urlsplit(source).path).name) or "result"
    out: Dict[str, Any] = {"saved": save(f"{number}_{name}", data)}
    shape = _table_shape(data, source)
    if shape:
        out["columns"], out["rows"] = shape
    return out


def fetch_result_files(template: Dict[str, Any], response_data: Any, success: bool,
                       save: Callable[[str, bytes], str]) -> List[Dict[str, Any]]:
    """Fetch and keep the files a run's responses link to, through ``save(name, data)``,
    which returns where the file went. One entry per block and call that returned. A
    file that cannot be had is an ``error`` in its entry: the run itself did happen."""
    blocks = [b for b in parse_outputs(template) if b.file_field]
    if not blocks:
        return []
    raw = template.get("connection") or {}
    conn = resolve_connection(raw)
    timeout = int(conn.get("timeout") or 60)
    base = expand_env(raw.get("file_base_url", ""))
    entries: List[Dict[str, Any]] = []
    fetched: Dict[str, Dict[str, Any]] = {}
    for number, call in enumerate(_answered_calls(response_data, success), start=1):
        for block in blocks:
            entry: Dict[str, Any] = {"component": block.component}
            instance = _instance_of(block, call)
            if instance:
                entry["instance"] = instance
            entries.append(entry)
            link = _read_field(call["response"], block.file_field)
            if not isinstance(link, str) or not link:
                entry["error"] = f"The response has no link in `{block.file_field}`."
                continue
            source = urljoin(base or call.get("url") or conn.get("url", ""), link)
            entry["source"] = source
            if source not in fetched:
                fetched[source] = _fetch_one(source, number, conn, timeout, save)
            entry.update(fetched[source])
            if "columns" in entry:
                entry["missing_columns"] = [a.field for a in block.attributes
                                            if a.field not in entry["columns"]]
    return entries


__all__ = ["MAX_FILE_BYTES", "fetch_result_files"]
