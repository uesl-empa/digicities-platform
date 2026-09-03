# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Service connection blocks: expansion, normalization, delivery, probing.

A service template's ``connection:`` block declares where the service listens
(transport + connection details). This module is the headless owner of that
block — ``${VAR:-default}`` expansion, normalization to a canonical dict for
either transport, payload delivery through the transport layer, and the
reachability probe. Ported from the Streamlit layer
(api_submission_module/api_config.py + submission_core.py) so the REST API
registers and submits exactly like the Streamlit tab does.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

from backend.api_submission.transports import TransportResult, submit_http, submit_redis

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}`` against the environment
    (compose-style), so one template serves multiple deployments."""
    if not isinstance(value, str):
        return value

    def repl(m: re.Match) -> str:
        var, default = m.group(1), m.group(3)
        return os.environ.get(var, default if default is not None else "")

    return _ENV_PATTERN.sub(repl, value)


def resolve_connection(conn: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A template's ``connection:`` block as a canonical, env-expanded dict.

    HTTP → ``{transport, url, method, headers, auth_type, auth_credentials,
    timeout}``; Redis → ``{transport, timeout, redis: {host, port,
    request_stream, result_stream, payload_field, request_id_field,
    encode_payload_as_json, poll_timeout}}``. Same defaults as the Streamlit
    registration (``service_api_from_connection``).
    """
    conn = conn or {}
    transport = str(conn.get("transport", "http")).lower()
    if transport == "redis":
        redis_cfg = {
            "host": expand_env(conn.get("host", "localhost")),
            "port": int(conn.get("port", 6379)),
            "request_stream": expand_env(conn.get("request_stream", "")),
            "result_stream": expand_env(conn.get("result_stream", "")),
            "payload_field": conn.get("payload_field", "payload"),
            "request_id_field": conn.get("request_id_field", "request_id"),
            "encode_payload_as_json": bool(conn.get("encode_payload_as_json", True)),
            "poll_timeout": int(conn.get("poll_timeout", conn.get("timeout", 120))),
        }
        return {"transport": "redis",
                "timeout": int(conn.get("timeout", redis_cfg["poll_timeout"])),
                "redis": redis_cfg}
    return {
        "transport": "http",
        "url": expand_env(conn.get("url", "")),
        "method": str(conn.get("method", "POST")).upper(),
        "headers": conn.get("headers", {}) or {},
        "auth_type": str(conn.get("auth_type", "none")),
        "auth_credentials": conn.get("auth_credentials", {}) or {},
        "timeout": int(conn.get("timeout", 60)),
    }


def auth_headers(resolved: Dict[str, Any]) -> Tuple[Dict[str, str], Optional[Tuple[str, str]]]:
    """(headers, basic-auth tuple) for a resolved HTTP connection."""
    headers = dict(resolved.get("headers") or {})
    auth = None
    creds = resolved.get("auth_credentials") or {}
    auth_type = resolved.get("auth_type", "none")
    if auth_type == "bearer" and "token" in creds:
        headers["Authorization"] = f"Bearer {creds['token']}"
    elif auth_type == "api_key" and "header_name" in creds and "api_key" in creds:
        headers[creds["header_name"]] = creds["api_key"]
    elif auth_type == "basic" and "username" in creds and "password" in creds:
        auth = (creds["username"], creds["password"])
    return headers, auth


def describe_endpoint(resolved: Dict[str, Any]) -> str:
    """One-line 'where does this go' string for results and UIs."""
    if resolved.get("transport") == "redis":
        rc = resolved.get("redis", {})
        return f"redis://{rc.get('host', 'localhost')}:{rc.get('port', 6379)}/{rc.get('request_stream', '')}"
    return resolved.get("url", "")


def submit_via_connection(payload: Dict[str, Any], conn: Optional[Dict[str, Any]]) -> TransportResult:
    """Deliver ``payload`` per the template's ``connection:`` block —
    the same dispatch the Streamlit submit tab performs."""
    resolved = resolve_connection(conn)
    if resolved["transport"] == "redis":
        rc = resolved["redis"]
        return submit_redis(
            payload,
            request_stream=rc["request_stream"],
            host=rc["host"],
            port=rc["port"],
            result_stream=rc["result_stream"] or None,
            payload_field=rc["payload_field"],
            request_id_field=rc["request_id_field"],
            encode_payload_as_json=rc["encode_payload_as_json"],
            poll_timeout=rc["poll_timeout"],
        )
    headers, auth = auth_headers(resolved)
    return submit_http(
        payload,
        url=resolved["url"],
        method=resolved["method"],
        headers=headers,
        auth=auth,
        timeout=resolved["timeout"],
    )


def test_connection(conn: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reachability probe: Redis PING, or an empty-body request where any
    status below 500 counts as reachable. Returns ``{ok, detail,
    status_code?}`` — never raises."""
    resolved = resolve_connection(conn)
    if resolved["transport"] == "redis":
        rc = resolved["redis"]
        try:
            import redis as _redis
        except ImportError:
            return {"ok": False, "detail": "The 'redis' package is not installed on the server."}
        try:
            client = _redis.Redis(host=rc["host"], port=rc["port"], socket_connect_timeout=5)
            client.ping()
            return {"ok": True, "detail": f"Connected to Redis at {rc['host']}:{rc['port']}."}
        except Exception as probe_error:
            return {"ok": False, "detail": f"Could not reach Redis: {probe_error}"}

    if not resolved["url"]:
        return {"ok": False, "detail": "The connection has no URL."}
    import requests

    headers, auth = auth_headers(resolved)
    try:
        response = requests.request(resolved["method"], resolved["url"],
                                    json={}, headers=headers, auth=auth, timeout=5)
    except requests.exceptions.ConnectionError:
        return {"ok": False, "detail": "Connection failed — could not reach the server."}
    except requests.exceptions.Timeout:
        return {"ok": False, "detail": "Connection timed out."}
    except Exception as probe_error:
        return {"ok": False, "detail": f"Test failed: {probe_error}"}
    if response.status_code < 500:
        return {"ok": True, "detail": f"Endpoint reachable (status {response.status_code}).",
                "status_code": response.status_code}
    return {"ok": False, "detail": f"Server error: {response.status_code}",
            "status_code": response.status_code}


__all__ = [
    "expand_env",
    "resolve_connection",
    "auth_headers",
    "describe_endpoint",
    "submit_via_connection",
    "test_connection",
]
