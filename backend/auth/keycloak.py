# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Keycloak / OIDC flow, headless.

Pure functions over explicit arguments — no Streamlit, no session state.
This is a faithful extraction of the flow the Streamlit ``components/auth.py``
has always run:

- authorization-code login URL (``response_type=code``, scope
  ``openid email profile``)
- code → token exchange and refresh-token grant against the realm's
  ``openid-connect/token`` endpoint
- token *payload* decoding by base64url (NO signature verification — exactly
  what the existing app does; it trusts tokens it received directly from
  Keycloak over TLS)
- expiry math: a token is treated as expired once it is past 90 % of its
  reported lifetime, so it gets refreshed before it actually lapses

``validate_token`` extends the same local, crypto-free check to
bearer tokens presented by third parties (the optional API auth): decodable
payload + unexpired ``exp`` claim. It deliberately does not introduce
signature verification or introspection the platform never had; swap it out
here when that hardening lands.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests

DEFAULT_TOKEN_LIFETIME = 28800  # seconds (8 h) — Keycloak default the app assumes
REFRESH_THRESHOLD = 0.9  # refresh once a token is past 90 % of its lifetime
OIDC_SCOPE = "openid email profile"


class TokenValidationError(Exception):
    """A bearer token failed the local validation check."""


@dataclass
class KeycloakConfig:
    """Realm coordinates, usually read from the KEYCLOAK_* env vars."""
    base_url: str
    realm: str
    client_id: str
    client_secret: str = ""
    redirect_uri: str = ""

    @classmethod
    def from_env(cls) -> "KeycloakConfig":
        return cls(
            base_url=os.getenv("KEYCLOAK_BASE_URL") or "",
            realm=os.getenv("KEYCLOAK_REALM") or "",
            client_id=os.getenv("KEYCLOAK_CLIENT_ID") or "",
            client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET") or "",
            redirect_uri=os.getenv("KEYCLOAK_REDIRECT_URI") or "",
        )

    @property
    def realm_url(self) -> str:
        return f"{self.base_url}/realms/{self.realm}"

    @property
    def auth_endpoint(self) -> str:
        return f"{self.realm_url}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.realm_url}/protocol/openid-connect/token"

    @property
    def logout_endpoint(self) -> str:
        return f"{self.realm_url}/protocol/openid-connect/logout"


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def build_login_url(config: KeycloakConfig, redirect_uri: Optional[str] = None) -> str:
    """The authorization-code login URL the browser is sent to."""
    redirect = redirect_uri or config.redirect_uri
    return (
        f"{config.auth_endpoint}?"
        f"response_type=code&"
        f"client_id={urllib.parse.quote(config.client_id)}&"
        f"redirect_uri={urllib.parse.quote(redirect)}&"
        f"scope={OIDC_SCOPE}"
    )


def build_logout_url(config: KeycloakConfig, redirect_uri: Optional[str] = None) -> str:
    """The Keycloak logout URL that lands the browser back on ``redirect_uri``."""
    redirect = redirect_uri or config.redirect_uri
    return f"{config.logout_endpoint}?redirect_uri={urllib.parse.quote(redirect)}"


# ---------------------------------------------------------------------------
# Token endpoint grants
# ---------------------------------------------------------------------------

def exchange_code(config: KeycloakConfig, code: str,
                  redirect_uri: Optional[str] = None) -> dict:
    """Exchange an authorization code for tokens. Raises on HTTP error.

    Returns the raw token response dict (``access_token``, ``refresh_token``,
    ``expires_in``, ...). ``redirect_uri`` must match the one used for login.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    res = requests.post(config.token_endpoint, data=data)
    res.raise_for_status()
    return res.json()


def refresh_access_token(config: KeycloakConfig, refresh_token: str) -> dict:
    """Redeem a refresh token for a fresh token set. Raises on HTTP error.

    Returns the raw token response dict; note Keycloak may rotate the
    refresh token, so callers must store the returned one.
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    res = requests.post(config.token_endpoint, data=data)
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# Token inspection (local, no crypto — see module docstring)
# ---------------------------------------------------------------------------

def decode_token_payload(access_token: str) -> dict:
    """Decode a JWT's payload segment (base64url). No signature verification."""
    payload_part = access_token.split(".")[1]
    padded = payload_part + "=" * (-len(payload_part) % 4)
    decoded = base64.urlsafe_b64decode(padded).decode()
    return json.loads(decoded)


def token_expires_at(token_timestamp: float, expires_in: float = DEFAULT_TOKEN_LIFETIME,
                     threshold: float = REFRESH_THRESHOLD) -> float:
    """The moment (epoch seconds) a token should be refreshed.

    That is ``threshold`` (default 90 %) of its lifetime past issue time —
    refresh early rather than ride the token to its literal expiry.
    """
    return token_timestamp + expires_in * threshold


def is_token_expired(token_timestamp: Optional[float],
                     expires_in: float = DEFAULT_TOKEN_LIFETIME,
                     threshold: float = REFRESH_THRESHOLD,
                     now: Optional[float] = None) -> bool:
    """True when the token is due for a refresh.

    ``token_timestamp`` is when the token was issued (epoch seconds). A
    missing timestamp counts as expired (legacy sessions predate tracking).
    """
    if not token_timestamp:
        return True
    if now is None:
        now = time.time()
    return now >= token_expires_at(token_timestamp, expires_in, threshold)


def validate_token(access_token: str, now: Optional[float] = None) -> dict:
    """Locally validate a bearer token: decodable payload, unexpired ``exp``.

    Returns the decoded payload on success; raises
    :class:`TokenValidationError` otherwise. Mirrors the trust model of the
    existing Streamlit flow (decode without signature verification) — see the
    module docstring before relying on this across a network boundary.
    """
    if not access_token:
        raise TokenValidationError("empty token")
    try:
        payload = decode_token_payload(access_token)
    except Exception as exc:
        raise TokenValidationError(f"token payload not decodable: {exc}") from exc
    exp = payload.get("exp")
    if exp is not None:
        if now is None:
            now = time.time()
        try:
            if now >= float(exp):
                raise TokenValidationError("token expired")
        except (TypeError, ValueError) as exc:
            raise TokenValidationError(f"malformed exp claim: {payload.get('exp')!r}") from exc
    return payload
