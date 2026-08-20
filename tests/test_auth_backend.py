# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The extracted auth backend (Phase 6) + the optional API auth dependency.

``backend.auth.keycloak`` is the headless home of the OIDC flow the Streamlit
shell has always run: login-URL construction, code→token exchange, refresh,
base64url payload decoding (no signature verification — the existing trust
model), and the 90 %-of-lifetime expiry math. These tests pin that behaviour
with canned unsigned JWTs and mocked HTTP.

API side: ``apps.api.auth.require_auth`` is OFF by default — with no env set
every route stays open (all pre-existing tests double as proof). Setting
``API_AUTH_ENABLED=1`` is the single switch that starts demanding a valid
Bearer token.
"""
from __future__ import annotations

import base64
import json
import time

import pytest

from backend.auth import (
    KeycloakConfig,
    TokenValidationError,
    build_login_url,
    build_logout_url,
    decode_token_payload,
    exchange_code,
    is_token_expired,
    refresh_access_token,
    token_expires_at,
    validate_token,
)


CONFIG = KeycloakConfig(
    base_url="https://kc.example.com",
    realm="digicities",
    client_id="digicities app",  # space on purpose: must be URL-encoded
    client_secret="s3cret",
    redirect_uri="https://platform.example.com/",
)


def _b64url(data: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return raw.rstrip("=")  # JWTs strip padding; the decoder must re-add it


def make_jwt(payload: dict) -> str:
    """A canned unsigned JWT — matches what the code actually inspects."""
    header = _b64url({"alg": "none", "typ": "JWT"})
    return f"{header}.{_b64url(payload)}.sig"


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def test_login_url_construction():
    url = build_login_url(CONFIG, "http://localhost:8501")
    assert url.startswith(
        "https://kc.example.com/realms/digicities/protocol/openid-connect/auth?")
    assert "response_type=code" in url
    assert "client_id=digicities%20app" in url
    assert "redirect_uri=http%3A//localhost%3A8501" in url
    assert "scope=openid email profile" in url


def test_login_url_defaults_to_config_redirect():
    assert "redirect_uri=https%3A//platform.example.com/" in build_login_url(CONFIG)


def test_logout_url_construction():
    url = build_logout_url(CONFIG, "http://localhost:8501")
    assert url == (
        "https://kc.example.com/realms/digicities/protocol/openid-connect/logout"
        "?redirect_uri=http%3A//localhost%3A8501")


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_BASE_URL", "https://kc.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "r1")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "cid")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "cs")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "https://app.example.com")
    cfg = KeycloakConfig.from_env()
    assert cfg.token_endpoint == (
        "https://kc.example.com/realms/r1/protocol/openid-connect/token")
    assert cfg.client_id == "cid" and cfg.client_secret == "cs"
    assert cfg.redirect_uri == "https://app.example.com"


# ---------------------------------------------------------------------------
# Payload decoding + expiry math
# ---------------------------------------------------------------------------

def test_decode_token_payload_roundtrip():
    payload = {"sub": "u-1", "preferred_username": "james", "groups": ["ws-a"]}
    assert decode_token_payload(make_jwt(payload)) == payload


def test_expiry_math_uses_90_percent_threshold():
    issued = 1_000_000.0
    # 8h token: refresh threshold at issued + 25920s
    assert token_expires_at(issued, 28800) == issued + 25920
    assert not is_token_expired(issued, 28800, now=issued + 25919)
    assert is_token_expired(issued, 28800, now=issued + 25920)


def test_missing_timestamp_counts_as_expired():
    # Legacy sessions predate timestamp tracking → always refresh.
    assert is_token_expired(None)
    assert is_token_expired(0)


def test_infinite_lifetime_never_expires():
    # AUTH_DISABLED local mode parks inf timestamps in session state.
    assert not is_token_expired(float("inf"), float("inf"))


# ---------------------------------------------------------------------------
# validate_token — local check: decodable payload + unexpired exp
# ---------------------------------------------------------------------------

def test_validate_token_accepts_unexpired():
    payload = {"sub": "u-1", "exp": time.time() + 3600}
    assert validate_token(make_jwt(payload))["sub"] == "u-1"


def test_validate_token_rejects_expired():
    token = make_jwt({"sub": "u-1", "exp": time.time() - 10})
    with pytest.raises(TokenValidationError, match="expired"):
        validate_token(token)


def test_validate_token_accepts_missing_exp():
    # Mirrors the Streamlit flow, which never reads exp; expiry is opt-in.
    assert validate_token(make_jwt({"sub": "u-1"}))["sub"] == "u-1"


@pytest.mark.parametrize("bad", ["", "garbage", "one.two", "a.!!!.c"])
def test_validate_token_rejects_undecodable(bad):
    with pytest.raises(TokenValidationError):
        validate_token(bad)


def test_validate_token_rejects_malformed_exp():
    with pytest.raises(TokenValidationError, match="exp"):
        validate_token(make_jwt({"sub": "u-1", "exp": "not-a-number"}))


# ---------------------------------------------------------------------------
# Token-endpoint grants — request construction (HTTP mocked)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_exchange_code_request_construction(monkeypatch):
    calls = {}

    def fake_post(url, data=None):
        calls["url"], calls["data"] = url, data
        return _FakeResponse({"access_token": "at", "refresh_token": "rt"})

    monkeypatch.setattr("backend.auth.keycloak.requests.post", fake_post)
    out = exchange_code(CONFIG, "the-code", "http://localhost:8501")

    assert out == {"access_token": "at", "refresh_token": "rt"}
    assert calls["url"] == CONFIG.token_endpoint
    assert calls["data"] == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "http://localhost:8501",
        "client_id": "digicities app",
        "client_secret": "s3cret",
    }


def test_refresh_request_construction(monkeypatch):
    calls = {}

    def fake_post(url, data=None):
        calls["url"], calls["data"] = url, data
        return _FakeResponse({"access_token": "at2"})

    monkeypatch.setattr("backend.auth.keycloak.requests.post", fake_post)
    out = refresh_access_token(CONFIG, "the-refresh-token")

    assert out == {"access_token": "at2"}
    assert calls["url"] == CONFIG.token_endpoint
    assert calls["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "the-refresh-token",
        "client_id": "digicities app",
        "client_secret": "s3cret",
    }


def test_exchange_code_raises_on_http_error(monkeypatch):
    class _Failing(_FakeResponse):
        def raise_for_status(self):
            raise RuntimeError("400 Bad Request")

    monkeypatch.setattr(
        "backend.auth.keycloak.requests.post", lambda url, data=None: _Failing({}))
    with pytest.raises(RuntimeError):
        exchange_code(CONFIG, "bad-code")


# ---------------------------------------------------------------------------
# API dependency: OFF by default, one env var to enforce
# ---------------------------------------------------------------------------

def test_api_open_access_when_env_unset(api_client, monkeypatch):
    monkeypatch.delenv("API_AUTH_ENABLED", raising=False)
    assert api_client.get("/health").status_code == 200


@pytest.mark.parametrize("falsy", ["", "0", "false", "off"])
def test_api_open_access_on_falsy_values(api_client, monkeypatch, falsy):
    monkeypatch.setenv("API_AUTH_ENABLED", falsy)
    assert api_client.get("/health").status_code == 200


def test_api_401_without_bearer_when_enabled(api_client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "1")
    r = api_client.get("/health")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate") == "Bearer"

    # Wrong scheme is also a 401.
    r = api_client.get("/health", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_api_401_on_invalid_token_when_enabled(api_client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")

    def reject(token):
        raise TokenValidationError("nope")

    monkeypatch.setattr("apps.api.auth.validate_token", reject)
    r = api_client.get("/health", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401


def test_api_200_with_valid_bearer_when_enabled(api_client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "1")
    monkeypatch.setattr(
        "apps.api.auth.validate_token", lambda token: {"sub": "u-1"})
    r = api_client.get("/health", headers={"Authorization": "Bearer good"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_real_token_end_to_end(api_client, monkeypatch):
    """No stub: a canned unexpired JWT passes the real local validator."""
    monkeypatch.setenv("API_AUTH_ENABLED", "yes")
    token = make_jwt({"sub": "u-1", "exp": time.time() + 3600})
    assert api_client.get(
        "/health", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    expired = make_jwt({"sub": "u-1", "exp": time.time() - 10})
    assert api_client.get(
        "/health", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_auth_dependency_is_appwide(api_client, monkeypatch):
    """The dependency guards every route, not just /health."""
    monkeypatch.setenv("API_AUTH_ENABLED", "1")
    assert api_client.get("/api/workspaces").status_code == 401
