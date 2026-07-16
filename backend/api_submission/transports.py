# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Transport layer for submitting a service payload to a registered service.

Pure-Python and UI-independent. Digicities builds a payload from a scenario via a
service's requirements template; *this* module is only responsible for delivering
that payload to wherever the service listens. Two transports are supported:

- ``submit_http``  — POST/PUT a JSON body to a configured HTTP endpoint (default).
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

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class TransportResult:
    """Outcome of a transport-level submission (HTTP or Redis)."""
    success: bool
    status_code: int = 0
    response_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    request_id: str = ""


def submit_http(
    payload: Dict[str, Any],
    *,
    url: str,
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[Tuple[str, str]] = None,
    timeout: int = 30,
) -> TransportResult:
    """POST/PUT ``payload`` as JSON to ``url``. Treats 200/201/202 as success."""
    import requests

    if not url:
        return TransportResult(False, error_message="No endpoint URL configured for this service.")

    method = (method or "POST").upper()
    if method not in ("POST", "PUT"):
        return TransportResult(False, error_message=f"Unsupported HTTP method: {method}")

    req_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
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
