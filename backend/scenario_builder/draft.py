# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""ScenarioDraft — the serializable input contract of the full scenario emitter.

The Streamlit Scenario Builder accumulates a scenario across ``st.session_state``
keys (``scenario_name``, ``scenario_components``, ``scenario_links``,
``required_attributes``, ``ttl_specificity``, ``current_workspace``,
``selected_requirements``). This dataclass captures exactly that shape as plain
data, so the emitter (:mod:`backend.scenario_builder.emitter`) can run headlessly
and the REST API can accept the same draft over the wire (platform issue #17).

Components and links stay the *session-state dicts* the emitter has always
consumed — this is deliberately not a re-modelling:

* component: ``{"uri", "type", "label", "source"?, "workspace_id"?,
  "source_catalog"?, "uri_fragment"?, "attributes"?, "nested_properties"?}``
  where ``attributes`` maps name -> ``{"value", "unit"?, "attribute_type"?,
  "temporal_value"?, "temporal_precision"?, "category_value"?, ...}`` and
  ``nested_properties`` maps attribute name -> ``{"hasHistoricTimeSeries"?,
  "hasHistoricTimeSeriesReference"?, "unit"?, ...}``.
* link: ``{"source", "target", "link_type"?}`` (``link_type`` absent = manual;
  ``"scenario_automatic"`` = scenario-to-component link).

Constructors:

* :meth:`from_session_state` — used by the Streamlit shim; reads the exact
  session keys the old ``generate_full_ttl()`` read.
* :meth:`from_request` — used by ``apps/api/scenario.py``; normalizes request
  dicts (drops ``None`` fields, defaults labels) and validates that every
  component carries the ``type`` the full emitter requires.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from backend.scenario_builder.display_utils import get_uri_fragment


@dataclass
class ScenarioDraft:
    scenario_name: str
    workspace_id: str = "default_workspace"
    workspace_name: Optional[str] = None
    service_name: Optional[str] = None
    description: Optional[str] = None
    ttl_specificity: str = "High"
    required_attributes: Dict[str, List[str]] = field(default_factory=dict)
    components: List[dict] = field(default_factory=list)
    links: List[dict] = field(default_factory=list)

    # ── serialization ─────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScenarioDraft":
        known = {f for f in cls.__dataclass_fields__}  # noqa: C401
        return cls(**{k: v for k, v in dict(data).items() if k in known})

    # ── constructors ──────────────────────────────────────────────────────
    @classmethod
    def from_session_state(cls, state: Mapping[str, Any]) -> "ScenarioDraft":
        """Build a draft from Streamlit session state (or any mapping with the
        same keys). Mirrors exactly what ``generate_full_ttl()`` used to read."""
        current_workspace = state.get("current_workspace")
        workspace_id = current_workspace["id"] if current_workspace else "default_workspace"
        workspace_name = current_workspace["name"] if current_workspace else "Default Workspace"
        service_name = (state.get("selected_requirements") or {}).get("service_name")
        return cls(
            scenario_name=state["scenario_name"],
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            service_name=service_name,
            description=None,  # the emitter derives it from the workspace name
            ttl_specificity=state.get("ttl_specificity", "High"),
            required_attributes=state.get("required_attributes", {}) or {},
            components=list(state.get("scenario_components", [])),
            links=list(state.get("scenario_links", [])),
        )

    @classmethod
    def from_request(
        cls,
        scenario_name: str,
        workspace_id: str,
        components: Sequence[Mapping[str, Any]],
        links: Sequence[Mapping[str, Any]] = (),
        *,
        workspace_name: Optional[str] = None,
        service_name: Optional[str] = None,
        description: Optional[str] = None,
        ttl_specificity: str = "High",
        required_attributes: Optional[Mapping[str, List[str]]] = None,
    ) -> "ScenarioDraft":
        """Build a draft from API-request shapes (see ``apps/api/scenario.py``).

        Normalizes each component/link into the session-state dict shape the
        emitter consumes: ``None`` fields are dropped (so the emitter's
        ``.get(..., default)`` fallbacks fire exactly as they do for the UI),
        and a missing ``label`` defaults to the URI fragment.

        Raises ``ValueError`` when a component has no ``type`` — the full
        emitter declares ``<uri> a dici_onto:{type}`` for every component.
        """
        norm_components: List[dict] = []
        for comp in components:
            comp = dict(comp)
            uri = comp.get("uri")
            if not uri:
                raise ValueError("every component needs a 'uri'")
            if not comp.get("type"):
                raise ValueError(f"component <{uri}> needs a 'type' for the full scenario emitter")
            normalized = {"uri": uri, "type": comp["type"],
                          "label": comp.get("label") or get_uri_fragment(uri)}
            for key in ("source", "workspace_id", "source_catalog", "uri_fragment",
                        "attributes", "nested_properties"):
                if comp.get(key) is not None:
                    normalized[key] = comp[key]
            norm_components.append(normalized)

        norm_links: List[dict] = []
        for link in links:
            link = dict(link)
            normalized = {"source": link["source"], "target": link["target"]}
            if link.get("link_type") is not None:
                normalized["link_type"] = link["link_type"]
            norm_links.append(normalized)

        return cls(
            scenario_name=scenario_name,
            workspace_id=workspace_id,
            workspace_name=workspace_name or workspace_id,
            service_name=service_name,
            description=description,
            ttl_specificity=ttl_specificity or "High",
            required_attributes=dict(required_attributes or {}),
            components=norm_components,
            links=norm_links,
        )


__all__ = ["ScenarioDraft"]
