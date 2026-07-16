# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Minimal API-key auth for the demo energy simulator.

This service was originally a cloud-deployed, API-key-protected endpoint. Run
locally as a bundled demo it defaults to OPEN (no key): set AUTH_ENABLED=true and
API_KEY=<key> to require one. Kept tiny on purpose — the demo has no users.
"""
import os
from functools import wraps

from flask import request, jsonify, current_app


def _auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "false").lower() == "true"


def _expected_key() -> str:
    return os.environ.get("API_KEY", "")


def _provided_key():
    header = os.environ.get("API_KEY_HEADER", "X-API-Key")
    if request.headers.get(header):
        return request.headers[header]
    auth = request.headers.get("Authorization", "")
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() in ("bearer", "apikey"):
        return parts[1]
    return request.args.get("api_key")


def require_api_key(f):
    """Require an API key only when AUTH_ENABLED=true; otherwise pass through."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _auth_enabled():
            return f(*args, **kwargs)
        expected = _expected_key()
        if not expected:
            current_app.logger.warning("AUTH_ENABLED=true but API_KEY not set.")
            return jsonify({"error": "Authentication not configured"}), 500
        if _provided_key() != expected:
            return jsonify({"error": "Unauthorized", "message": "Valid API key required."}), 401
        return f(*args, **kwargs)
    return wrapper
