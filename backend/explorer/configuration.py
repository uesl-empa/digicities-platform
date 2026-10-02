# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Service configuration: the settings a model needs to run.

A configuration parameter (``ConfigurationAttribute``) is a boundary condition
of a model run (a model choice, a calibration constant, a run name, a stream
address), not an observation or behaviour of a component. Parameters are
grouped in ``ServiceConfiguration`` profiles owned by one ``Service``
(``hasConfiguration``); a profile names the components it is tuned for with
``appliesTo``. They live in the ``<services>`` graph, loaded from the
workspace's ``services/*.ttl``.

The explorer shows a component's configuration the way it shows data sources:
as extra columns behind a toggle, one per parameter and service
(``ModelType (WindForecaster)``), so a setting is never mistaken for a property
of the component.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from backend.graphdb.graphs import (
    CLASSES_AND_ATTRIBUTES_GRAPH,
    ONTOLOGY_GRAPH,
    SERVICES_GRAPH,
    from_clause,
)
from backend.graphdb.queries._exec import run_df

from .units import map_unit_uri_to_string

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX qudt: <http://qudt.org/schema/qudt/>\n"
)

_COLUMNS = ["instance", "service", "serviceLabel", "profile", "profileLabel",
            "param", "paramClass", "num", "unit", "unitLabel", "simple", "cat", "catLabel"]


def _local(iri: Any) -> str:
    s = str(iri or "")
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _present(v: Any) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v) != ""


def format_value(row: Dict[str, Any]) -> str:
    """A parameter's value as one cell: ``0.0324555``, ``20 s``, the category's
    label, or the literal."""
    if _present(row.get("num")):
        unit = (map_unit_uri_to_string(str(row["unit"])) if _present(row.get("unit"))
                else str(row["unitLabel"]) if _present(row.get("unitLabel")) else "")
        return f"{row['num']} {unit}".strip()
    if _present(row.get("cat")):
        return str(row["catLabel"]) if _present(row.get("catLabel")) else _local(row["cat"])
    if _present(row.get("simple")):
        return str(row["simple"])
    return ""


def _records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for _, r in df.iterrows():
        row = r.to_dict()
        key = (str(row.get("instance") or ""), str(row.get("profile")), str(row.get("param")))
        if key in seen:
            continue
        seen.add(key)
        service = (str(row["serviceLabel"]) if _present(row.get("serviceLabel"))
                   else _local(row.get("service")) if _present(row.get("service")) else "")
        out.append({
            "instance": str(row.get("instance") or ""),
            "service": service,
            "service_uri": str(row.get("service") or "") if _present(row.get("service")) else "",
            "profile": (str(row["profileLabel"]) if _present(row.get("profileLabel"))
                        else _local(row.get("profile"))),
            "profile_uri": str(row.get("profile") or ""),
            "parameter": _local(row.get("paramClass")),
            "value": format_value(row),
        })
    return out


def get_component_configuration(client, component_type_label: str) -> List[Dict[str, Any]]:
    """The configuration parameters of every profile that ``appliesTo`` an
    instance of this component type. One record per instance × parameter:
    ``{instance, service, service_uri, profile, profile_uri, parameter, value}``.
    Never raises: no services graph, no profiles → ``[]``."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT {' '.join('?' + c for c in _COLUMNS)}
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH, SERVICES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
      ?profile dici_onto:appliesTo ?instance ;
               dici_onto:hasConfigurationParameter ?param .
      OPTIONAL {{ ?profile rdfs:label ?profileLabel . }}
      OPTIONAL {{ ?service dici_onto:hasConfiguration ?profile .
                 OPTIONAL {{ ?service rdfs:label ?serviceLabel . }} }}
      ?param a ?paramClass .
      ?paramClass rdfs:subClassOf* dici_onto:ConfigurationAttribute .
      FILTER(?paramClass != dici_onto:ConfigurationAttribute)
      OPTIONAL {{ ?param qudt:value ?num . }}
      OPTIONAL {{ ?param qudt:unit ?unit . }}
      OPTIONAL {{ ?param dici_onto:hasUnitLabel ?unitLabel . }}
      OPTIONAL {{ ?param dici_onto:hasAttributeValue ?simple . }}
      OPTIONAL {{ ?param dici_onto:hasCategoricalValue ?cat .
                 OPTIONAL {{ ?cat rdfs:label ?catLabel . }} }}
    }}
    """
    return _records(run_df(client, query, _COLUMNS))


def get_service_configurations(client) -> List[Dict[str, Any]]:
    """Every configuration profile in the workspace, with its parameters and
    the components it applies to: ``[{service, service_uri, profile,
    profile_uri, applies_to: [uri…], parameters: [{parameter, value}]}]``."""
    cols = [c for c in _COLUMNS if c != "instance"] + ["target"]
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT {' '.join('?' + c for c in cols)}
    {from_clause(ONTOLOGY_GRAPH, SERVICES_GRAPH)}WHERE {{
      ?profile a dici_onto:ServiceConfiguration ;
               dici_onto:hasConfigurationParameter ?param .
      OPTIONAL {{ ?profile rdfs:label ?profileLabel . }}
      OPTIONAL {{ ?profile dici_onto:appliesTo ?target . }}
      OPTIONAL {{ ?service dici_onto:hasConfiguration ?profile .
                 OPTIONAL {{ ?service rdfs:label ?serviceLabel . }} }}
      ?param a ?paramClass .
      ?paramClass rdfs:subClassOf* dici_onto:ConfigurationAttribute .
      FILTER(?paramClass != dici_onto:ConfigurationAttribute)
      OPTIONAL {{ ?param qudt:value ?num . }}
      OPTIONAL {{ ?param qudt:unit ?unit . }}
      OPTIONAL {{ ?param dici_onto:hasUnitLabel ?unitLabel . }}
      OPTIONAL {{ ?param dici_onto:hasAttributeValue ?simple . }}
      OPTIONAL {{ ?param dici_onto:hasCategoricalValue ?cat .
                 OPTIONAL {{ ?cat rdfs:label ?catLabel . }} }}
    }}
    """
    df = run_df(client, query, cols)
    profiles: Dict[str, Dict[str, Any]] = {}
    for _, r in df.iterrows():
        rec = _records(pd.DataFrame([r]))[0]
        p = profiles.setdefault(rec["profile_uri"], {
            "service": rec["service"], "service_uri": rec["service_uri"],
            "profile": rec["profile"], "profile_uri": rec["profile_uri"],
            "applies_to": [], "parameters": []})
        target = r.get("target")
        if _present(target) and str(target) not in p["applies_to"]:
            p["applies_to"].append(str(target))
        if not any(x["parameter"] == rec["parameter"] for x in p["parameters"]):
            p["parameters"].append({"parameter": rec["parameter"], "value": rec["value"]})
    return sorted(profiles.values(), key=lambda p: (p["service"], p["profile"]))


def config_column(parameter: str, service: str) -> str:
    """The explorer column for one parameter of one service."""
    return f"{parameter} ({service})" if service else parameter


def attach_configuration(df: pd.DataFrame, records: List[Dict[str, Any]]):
    """Add one column per (parameter, service) to the component table, keyed
    by the instance URI. Returns ``(df, config_columns, per_instance)``;
    ``per_instance`` maps instance URI → its records (for the detail panel)."""
    if df.empty or not records or "URI" not in df.columns:
        return df, [], {}
    df = df.copy()
    per: Dict[str, List[Dict[str, Any]]] = {}
    cols: List[str] = []
    for rec in records:
        per.setdefault(rec["instance"], []).append(rec)
        c = config_column(rec["parameter"], rec["service"])
        if c not in cols:
            cols.append(c)
    for c in cols:
        df[c] = df["URI"].map(lambda u, c=c: next(
            (r["value"] for r in per.get(str(u), [])
             if config_column(r["parameter"], r["service"]) == c), ""))
    return df, cols, per
