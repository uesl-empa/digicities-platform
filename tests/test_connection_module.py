# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""backend.api_submission.connection — expansion, normalization, auth mapping
(ported from the Streamlit registration; these pin the parity)."""
from __future__ import annotations

from backend.api_submission.connection import (
    auth_headers,
    describe_endpoint,
    expand_env,
    resolve_connection,
)


def test_expand_env_default_and_override(monkeypatch):
    monkeypatch.delenv("SVC_URL", raising=False)
    assert expand_env("${SVC_URL:-http://fallback:1}") == "http://fallback:1"
    monkeypatch.setenv("SVC_URL", "http://real:2")
    assert expand_env("${SVC_URL:-http://fallback:1}") == "http://real:2"
    # Unset var without default expands to empty; non-strings pass through.
    monkeypatch.delenv("NOPE_VAR", raising=False)
    assert expand_env("x-${NOPE_VAR}-y") == "x--y"
    assert expand_env(42) == 42


def test_resolve_http_defaults():
    r = resolve_connection({"url": "http://svc/run", "method": "post"})
    assert r == {"transport": "http", "url": "http://svc/run", "method": "POST",
                 "headers": {}, "auth_type": "none", "auth_credentials": {},
                 "timeout": 60}
    assert describe_endpoint(r) == "http://svc/run"


def test_resolve_redis_defaults():
    r = resolve_connection({"transport": "redis", "host": "h",
                            "request_stream": "req", "timeout": 30})
    assert r["transport"] == "redis" and r["timeout"] == 30
    rc = r["redis"]
    assert rc["port"] == 6379 and rc["payload_field"] == "payload"
    assert rc["request_id_field"] == "request_id"
    assert rc["encode_payload_as_json"] is True
    assert rc["poll_timeout"] == 30  # falls back to timeout
    assert describe_endpoint(r) == "redis://h:6379/req"


def test_auth_headers_mapping():
    h, a = auth_headers({"auth_type": "bearer", "auth_credentials": {"token": "t1"},
                         "headers": {"X-Extra": "1"}})
    assert h == {"X-Extra": "1", "Authorization": "Bearer t1"} and a is None

    h, a = auth_headers({"auth_type": "api_key",
                         "auth_credentials": {"header_name": "X-API-Key", "api_key": "k"}})
    assert h == {"X-API-Key": "k"} and a is None

    h, a = auth_headers({"auth_type": "basic",
                         "auth_credentials": {"username": "u", "password": "p"}})
    assert h == {} and a == ("u", "p")

    h, a = auth_headers({"auth_type": "none", "auth_credentials": {"token": "ignored"}})
    assert h == {} and a is None
