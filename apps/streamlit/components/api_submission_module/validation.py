# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: payload validation moved to ``backend.api_submission.validation``.

Only the Streamlit report renderer stays here.
"""

import streamlit as st

from backend.api_submission.validation import (  # noqa: F401
    ValidationResult,
    validate_payload,
)


def render_validation(vr: ValidationResult, container=None) -> None:
    """Render a validation report in the Streamlit UI."""
    target = container or st

    if vr.is_valid and not vr.warnings:
        target.success("✅ Validation passed. Every attribute the service needs resolved to a value.")
        return

    if not vr.is_valid:
        target.error(f"🔴 Validation failed ({len(vr.errors)} blocking issue(s)). This scenario cannot be submitted as-is.")
        for err in vr.errors:
            target.write(f"- {err}")

    if vr.warnings:
        target.warning(
            f"⚠️ {len(vr.warnings)} attribute(s) did not resolve. The service may fall back to "
            f"defaults, which can produce a confident but meaningless result."
        )
        for warn in vr.warnings:
            target.write(f"- {warn}")
