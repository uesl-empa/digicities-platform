# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Transport layer for submitting a service payload to a registered service.

Pure-Python and UI-independent. Digicities builds a payload from a scenario via a
service's requirements template; *this* module is only responsible for delivering
that payload to wherever the service listens. Two transports are supported:

- ``submit_http``  — POST/PUT a JSON body to a configured HTTP endpoint (default), or
  GET, where the request travels in the URL: one call per component.
- ``submit_redis`` — publish the payload to a Redis request stream and, optionally,
  poll a result stream for the matching ``request_id``.

This keeps Digicities decoupled from any particular stack: a service is described
by *where* it listens (transport + connection details) and *what shape* it wants
(its requirements template), both supplied at registration time — nothing here is
specific to the RDP stack or the flexibility optimizer.

``redis`` is an optional dependency: ``submit_redis`` returns a clear error instead
of raising if it isn't installed.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlsplit

# A field a GET url names: http://host/simulate/{pc6}
_PATH_FIELD = re.compile(r"\{(\w+)\}")
# What every payload may carry beside the request: not fields of it.
_NOT_REQUEST_FIELDS = ("service_name", "description", "units")


@dataclass
class TransportResult:
    """Outcome of a transport-level submission (HTTP or Redis)."""
    success: bool
    status_code: int = 0
    response_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    request_id: str = ""


def _flatten(node: Dict[str, Any], path: str, lists: List[Tuple[str, list]]) -> Dict[str, Any]:
    """A block's fields by their own names, whatever blocks hold them. A field nearer
    the component wins. Lists are set aside in ``lists``."""
    fields: Dict[str, Any] = {}
    for key, value in node.items():
        here = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            fields.update(_flatten(value, here, lists))
        elif isinstance(value, list):
            lists.append((here, value))
        else:
            fields[key] = value
    return fields


def url_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The payload as the flat records a URL can carry, one per call.

    A component list makes one call per component; the fields outside it go with
    every call. A URL holds single values, so a payload that needs more (two component
    lists, a list inside a component, a series) raises ValueError saying which field."""
    lists: List[Tuple[str, list]] = []
    shared = _flatten({k: v for k, v in payload.items() if k not in _NOT_REQUEST_FIELDS}, "", lists)
    if not lists:
        return [shared]
    if len(lists) > 1:
        raise ValueError(f"A GET request can carry one list of components, and this payload has "
                         f"{len(lists)}: {', '.join(path for path, _ in lists)}.")
    path, items = lists[0]
    records = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"`{path}` is a list of values, which a GET request cannot carry.")
        inner: List[Tuple[str, list]] = []
        records.append({**shared, **_flatten(item, path, inner)})
        if inner:
            raise ValueError(f"`{inner[0][0]}` is a list inside a component, which a GET request "
                             "cannot carry.")
    return records


def _fill_url(url: str, record: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """(the url with its ``{field}`` parts filled, the fields left for the query)."""
    named = _PATH_FIELD.findall(url)
    missing = [name for name in named if record.get(name) is None]
    if missing:
        raise ValueError(f"The URL needs {', '.join(missing)}, and the request has no such value.")
    filled = _PATH_FIELD.sub(lambda m: quote(str(record[m.group(1)]), safe=""), url)
    return filled, {k: v for k, v in record.items() if k not in named}


def _refuse_link_local(url: str) -> None:
    """A GET hands back what it reads, and a link-local address is where a cloud host
    serves its own credentials. No service lives there."""
    import requests

    host = urlsplit(url).hostname
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)} if host else set()
    except OSError:
        return  # the request itself reports a name that does not resolve
    if any(ipaddress.ip_address(a.split("%")[0]).is_link_local for a in addresses):
        raise requests.exceptions.InvalidURL(f"{host} is a link-local address, which is not a service.")


def safe_get(url: str, **kwargs: Any) -> Any:
    """``requests`` GET that will not read a link-local address, directly or by redirect."""
    import requests

    def check_redirect(response: Any, **_: Any) -> None:
        if response.is_redirect:
            _refuse_link_local(urljoin(response.url, response.headers["location"]))

    _refuse_link_local(url)
    return requests.request("GET", url, hooks={"response": check_redirect}, **kwargs)


def _call_http(
    method: str,
    url: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[Tuple[str, str]] = None,
    timeout: int = 30,
) -> TransportResult:
    """One HTTP call: a JSON body, or for GET the query. Treats 200/201/202 as success."""
    import requests

    try:
        if method == "GET":
            resp = safe_get(url, params=params, headers=headers or {}, auth=auth, timeout=timeout)
        else:
            req_headers = {"Content-Type": "application/json", **(headers or {})}
            resp = requests.request(method, url, json=payload, headers=req_headers, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        return TransportResult(False, error_message=f"Request timed out after {timeout}s.")
    except requests.exceptions.ConnectionError:
        return TransportResult(False, error_message=(
            "Connection error — could not reach the endpoint. Is the service container running "
            "and the URL correct?"))
    except requests.exceptions.RequestException as exc:
        return TransportResult(False, error_message=f"Request error: {exc}")

    out = TransportResult(success=False, status_code=resp.status_code)
    try:
        out.response_data = resp.json()
    except ValueError:
        out.response_data = {"response_text": resp.text}

    # A JSON body may explicitly report success/failure; otherwise fall back to the
    # HTTP status. Note: only a 2xx status counts — a non-JSON 200 is still success,
    # but a 4xx/5xx is always a failure even if the body parsed.
    body = out.response_data if isinstance(out.response_data, dict) else {}
    if resp.status_code in (200, 201, 202):
        out.success = body.get("success", True)
    else:
        out.success = False
    if not out.success and not out.error_message:
        out.error_message = f"Endpoint returned status {resp.status_code}: {resp.text[:500]}"
    return out


def _submit_get(
    payload: Dict[str, Any],
    url: str,
    headers: Optional[Dict[str, str]],
    auth: Optional[Tuple[str, str]],
    timeout: int,
) -> TransportResult:
    """One GET per record of the payload. ``response_data`` is ``{"calls": [...]}``: what
    each call asked, and what came back. A request that cannot be made sends nothing."""
    try:
        records = url_records(payload)
        targets = [_fill_url(url, record) for record in records]
    except ValueError as exc:
        return TransportResult(False, error_message=str(exc))
    if not records:
        return TransportResult(False, error_message="The payload has no components to request.")

    calls: List[Dict[str, Any]] = []
    failed: List[TransportResult] = []
    for record, (target, params) in zip(records, targets):
        result = _call_http("GET", target, params=params, headers=headers, auth=auth, timeout=timeout)
        calls.append({"request": record, "url": target, "status_code": result.status_code,
                      "response": result.response_data})
        if not result.success:
            calls[-1]["error"] = result.error_message
            failed.append(result)
        if not result.status_code:
            break  # no answer at all: the next call would not get one either
    out = TransportResult(not failed, (failed[0] if failed else result).status_code, {"calls": calls})
    if failed:
        out.error_message = (f"{len(failed)} of {len(records)} calls failed, and {len(records) - len(calls)} "
                             f"were not made. First failure: {failed[0].error_message}")
    return out


def submit_http(
    payload: Dict[str, Any],
    *,
    url: str,
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[Tuple[str, str]] = None,
    timeout: int = 30,
) -> TransportResult:
    """POST/PUT ``payload`` as JSON to ``url``, or GET it through the URL (``_submit_get``)."""
    if not url:
        return TransportResult(False, error_message="No endpoint URL configured for this service.")

    method = (method or "POST").upper()
    if method == "GET":
        return _submit_get(payload, url, headers, auth, timeout)
    if method not in ("POST", "PUT"):
        return TransportResult(False, error_message=f"Unsupported HTTP method: {method}")
    return _call_http(method, url, payload=payload, headers=headers, auth=auth, timeout=timeout)


def submit_redis(
    payload: Dict[str, Any],
    *,
    request_stream: str,
    host: str = "localhost",
    port: int = 6379,
    result_stream: Optional[str] = None,
    payload_field: str = "payload",
    request_id_field: str = "request_id",
    encode_payload_as_json: bool = True,
    request_id: Optional[str] = None,
    poll_timeout: int = 120,
) -> TransportResult:
    """Publish ``payload`` to a Redis stream; optionally poll for a result.

    The message is ``{request_id_field: <id>, payload_field: <payload>}``. When
    ``encode_payload_as_json`` is true (the default) the payload is JSON-encoded
    into a single field — the convention several stream consumers use (e.g. a
    ``buildings`` field carrying a JSON array). If ``result_stream`` is given, the
    call blocks until a message with a matching ``request_id`` appears (or the
    timeout elapses).
    """
    try:
        import redis as _redis
    except ImportError:
        return TransportResult(False, error_message=(
            "The 'redis' package is not installed, so the Redis transport is unavailable. "
            "Install it (pip install redis) or use the HTTP transport."))

    if not request_stream:
        return TransportResult(False, error_message="No Redis request stream configured for this service.")

    rid = request_id or f"digicities-{uuid.uuid4().hex[:12]}"
    out = TransportResult(success=False, request_id=rid)

    try:
        client = _redis.Redis(host=host, port=int(port), decode_responses=True)
        # Capture the result stream's current tail BEFORE publishing, so we catch a
        # reply even if the service answers before our first poll (fast services),
        # without replaying old results. "0-0" means "from the start" (empty stream).
        result_from_id = "0-0"
        if result_stream:
            try:
                tail = client.xrevrange(result_stream, count=1)
                result_from_id = tail[0][0] if tail else "0-0"
            except Exception:
                result_from_id = "0-0"
        field_value = json.dumps(payload) if encode_payload_as_json else payload
        message = {request_id_field: rid, payload_field: field_value}
        message_id = client.xadd(request_stream, message)
    except Exception as exc:
        out.error_message = (
            f"Could not publish to Redis stream '{request_stream}' at {host}:{port}: {exc}")
        return out

    if not result_stream:
        out.success = True
        out.response_data = {
            "published_to": request_stream,
            "message_id": str(message_id),
            "request_id": rid,
            "note": "Published; no result stream configured so not waiting for a result.",
        }
        return out

    # Poll the result stream for a message tagged with our request_id, starting
    # from the tail captured before publishing. Each read blocks only briefly, so
    # it stays well under any idle-connection limit imposed by a Docker host proxy
    # (services reached via host.docker.internal). Transient read timeouts are
    # tolerated: we keep polling until poll_timeout rather than aborting on the
    # first hiccup.
    last_id = result_from_id
    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        try:
            entries = client.xread({result_stream: last_id}, count=10, block=1000)
        except Exception:
            # Transient read timeout / dropped idle connection — retry until deadline.
            time.sleep(0.2)
            continue
        for _stream, messages in (entries or []):
            for msg_id, fields in messages:
                last_id = msg_id
                if fields.get(request_id_field) == rid:
                    decoded = _decode_result_fields(fields)
                    # A service may explicitly report failure via a success/error field.
                    ok = str(decoded.get("success", "true")).lower() not in ("false", "0", "no")
                    out.success = ok
                    out.response_data = decoded
                    if not ok:
                        out.error_message = str(decoded.get("error", "")) or "Service reported failure."
                    return out

    out.error_message = (
        f"No result for request_id '{rid}' on stream '{result_stream}' within {poll_timeout}s "
        "(the request was published — the service may still be processing).")
    return out


def _decode_result_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort: JSON-decode any string field that looks like JSON."""
    decoded: Dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, str) and value[:1] in ("{", "["):
            try:
                decoded[key] = json.loads(value)
                continue
            except ValueError:
                pass
        decoded[key] = value
    return decoded
