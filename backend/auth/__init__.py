# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Authentication backend (Keycloak / OIDC), headless.

The OIDC mechanics — login-URL construction, code→token exchange, refresh,
payload decoding, expiry math — live in :mod:`backend.auth.keycloak` as pure
functions over explicit arguments. The Streamlit shell
(``components/auth.py``) and the optional REST-API dependency
(``apps/api/auth.py``) are thin glue over these.
"""
from .keycloak import (
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

__all__ = [
    "KeycloakConfig",
    "TokenValidationError",
    "build_login_url",
    "build_logout_url",
    "decode_token_payload",
    "exchange_code",
    "is_token_expired",
    "refresh_access_token",
    "token_expires_at",
    "validate_token",
]
