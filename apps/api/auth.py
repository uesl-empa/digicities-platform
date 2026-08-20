"""Optional bearer-token authentication for the REST API. OFF by default.

Decision (James): *extract, don't enforce*. Local mode stays open — exactly
like the Streamlit app under ``AUTH_DISABLED=true`` — so every existing
deployment and test runs unchanged with no env vars set.

Flipping enforcement on is one step: set ``API_AUTH_ENABLED=1`` (or
``true``/``yes``/``on``). From then on every request must carry
``Authorization: Bearer <token>`` where the token passes
``backend.auth.validate_token`` (locally decodable payload with an unexpired
``exp`` claim — the same trust model the Streamlit flow uses; see
``backend/auth/keycloak.py`` before exposing this across a network boundary).

``require_auth`` is installed as an app-level dependency in ``main.py``. It
reads the header off the raw ``Request`` rather than declaring a
``Header(...)`` parameter, so it adds nothing to the OpenAPI schema and the
frozen v1 snapshot stays byte-identical.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request

from backend.auth import TokenValidationError, validate_token

_TRUTHY = {"1", "true", "yes", "on"}


def auth_enabled() -> bool:
    """Read the switch per request so tests (and ops) can flip it live."""
    return os.getenv("API_AUTH_ENABLED", "").strip().lower() in _TRUTHY


@dataclass
class Principal:
    """Who is making the request. Anonymous unless enforcement is on."""
    subject: str = "anonymous"
    payload: dict[str, Any] = field(default_factory=dict)
    authenticated: bool = False


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_auth(request: Request) -> Principal:
    """App-level dependency: validate the Bearer token when enforcement is on.

    With ``API_AUTH_ENABLED`` unset/falsy this is a no-op returning an
    anonymous principal — the default, open-access mode.
    """
    if not auth_enabled():
        return Principal()

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Missing bearer token")

    try:
        payload = validate_token(token.strip())
    except TokenValidationError as exc:
        raise _unauthorized(f"Invalid token: {exc}") from exc

    return Principal(
        subject=str(payload.get("sub") or payload.get("preferred_username") or "unknown"),
        payload=payload,
        authenticated=True,
    )
