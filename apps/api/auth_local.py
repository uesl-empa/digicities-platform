# SPDX-License-Identifier: Apache-2.0
"""Local user accounts: register / login (JWT) + a current-user dependency.

Phase 2 of the workspaces RFC. Auth is NOT enforced here — endpoints keep working
without a token (owner/visibility filtering just falls back to "show everything").
Enforcement is flipped on in phase 3 via ``API_AUTH_ENABLED``. Requires the metadata
DB (``DATABASE_URL``); with no DB the register/login routes return 503 and the
current-user dependency yields None.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.db.session import db_enabled
from backend.db import users_repo

router = APIRouter(prefix="/api/auth", tags=["auth"])

_JWT_ALG = "HS256"
_TOKEN_TTL = int(os.getenv("JWT_TTL_SECONDS", str(30 * 24 * 3600)))


_DEV_SECRET = "dev-insecure-secret-change-me-in-production"


def _secret() -> str:
    # `or` (not getenv's default): compose passes JWT_SECRET="" when the host var is unset, and a
    # set-but-empty value would sail past a default and make jwt.encode raise "HMAC key must not be
    # empty" — a 500 on every login. Treat empty as absent → fall back to the dev secret.
    return os.getenv("JWT_SECRET") or _DEV_SECRET


def bootstrap() -> None:
    """Startup: warn loudly if login is enforced on the insecure default secret, and seed the
    first admin from ``ADMIN_EMAIL`` / ``ADMIN_PASSWORD`` (idempotent). Safe to call always."""
    import logging
    log = logging.getLogger("digicities.auth")
    if auth_required() and _secret() == _DEV_SECRET:
        log.warning("REQUIRE_LOGIN is on but JWT_SECRET is unset — using the INSECURE dev default. "
                    "Set JWT_SECRET to a long random value in production.")
    email = os.getenv("ADMIN_EMAIL", "").strip()
    pw = os.getenv("ADMIN_PASSWORD", "")
    if email and pw and db_enabled() and not users_repo.get_by_email(email):
        if users_repo.create_user(email, hash_password(pw), os.getenv("ADMIN_NAME", "Admin")):
            log.info("Seeded admin account %s", email)


def auth_required() -> bool:
    """When true (``REQUIRE_LOGIN``), a signed-in user is required to see or open any workspace —
    a signed-out caller gets 401 on the workspace routes (``/health`` and ``/api/auth/*`` stay
    open). When false, the app is open (a signed-out caller sees the shared workspaces only).

    NB: this is the JWT-account scheme's own switch — distinct from ``API_AUTH_ENABLED``, which
    drives the older static-bearer app-level guard in ``auth.py``. Don't reuse that one here or
    it gates ``/health`` too."""
    return os.getenv("REQUIRE_LOGIN", "").strip().lower() in ("1", "true", "yes", "on")


def hash_password(pw: str) -> str:
    import bcrypt
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def make_token(user_id: str) -> str:
    import jwt
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + _TOKEN_TTL}, _secret(), algorithm=_JWT_ALG)


def _decode(token: str) -> Optional[str]:
    import jwt
    try:
        return jwt.decode(token, _secret(), algorithms=[_JWT_ALG]).get("sub")
    except Exception:
        return None


def current_user_optional(request: Request) -> Optional[dict]:
    """The authenticated user (dict) from a Bearer token, or None (no/invalid token,
    or DB disabled). Never raises — filtering degrades to 'show everything'."""
    if not db_enabled():
        return None
    auth = request.headers.get("Authorization", "")
    # Header first; fall back to a ?token= query param for EventSource/SSE, which can't set
    # an Authorization header (the agent chat stream authenticates this way).
    tok = (auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ")
           else request.query_params.get("token"))
    uid = _decode(tok) if tok else None
    return users_repo.get_user(uid) if uid else None


class _Register(BaseModel):
    email: str
    password: str
    display_name: str = ""


class _Login(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(body: _Register) -> dict:
    if not db_enabled():
        raise HTTPException(503, "Accounts require the metadata database (DATABASE_URL).")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if users_repo.get_by_email(body.email):
        raise HTTPException(409, "An account with that email already exists.")
    u = users_repo.create_user(str(body.email), hash_password(body.password), body.display_name)
    if not u:
        raise HTTPException(500, "Could not create the account.")
    return {"token": make_token(u["id"]), "user": {"id": u["id"], "email": u["email"],
                                                    "display_name": u["display_name"]}}


@router.post("/login")
def login(body: _Login) -> dict:
    if not db_enabled():
        raise HTTPException(503, "Accounts require the metadata database (DATABASE_URL).")
    u = users_repo.get_by_email(body.email)
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid email or password.")
    return {"token": make_token(u["id"]), "user": {"id": u["id"], "email": u["email"],
                                                    "display_name": u["display_name"]}}


@router.get("/me")
def me(user: Optional[dict] = Depends(current_user_optional)) -> dict:
    if not user:
        raise HTTPException(401, "Not authenticated.")
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}
