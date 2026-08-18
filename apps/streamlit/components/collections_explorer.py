# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Collections — dataset-level statistics over attribute values.

Thin UI shell over ``backend.collections``: pick an attribute type (optionally
a grouping attribute and/or a data-source filter), materialize the Set /
GroupedSet into the ``<http://collections>`` named graph, and browse the
resulting descriptive statistics and distributions. All SPARQL and statistics
live in the backend module; this file only renders.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from backend.collections import (
    CollectionError,
    delete_collection,
    list_collections,
    materialize_grouped_set,
    materialize_set,
    member_count,
    set_bins,
    set_statistics,
    workspace_attribute_types,
    workspace_datasets,
)


def _local(iri) -> str:
    return str(iri).rstrip("#/").split("#")[-1].split("/")[-1]


def _workspace_id() -> str:
    ws = st.session_state.get("current_workspace")
    if isinstance(ws, dict):
        return ws.get("id", "")
    return str(ws or "")


def _stats_table(stats_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot the (set, groupKey, statistic, value) rows into one row per set,
    one column per statistic."""
    df = stats_df.copy()
    df["statistic"] = df["statistic"].map(_local)
    # Multi-valued statistics (tied modes) join into one cell.
    df = (df.groupby(["set", "groupKey", "statistic"], dropna=False)["value"]
            .apply(lambda v: ", ".join(sorted(map(str, v))))
            .reset_index())
    wide = df.pivot_table(index=["set", "groupKey"], columns="statistic",
                          values="value", aggfunc="first").reset_index()
    wide["set"] = wide["set"].map(_local)
    return wide


def _render_collection(client, row) -> None:
    coll = str(row["collection"])
    kind = _local(row["kind"])
    title = _local(coll)
    subtitle = [f"attribute: `{_local(row['attrType'])}`"]
    if pd.notna(row.get("groupedBy")) and row.get("groupedBy"):
        subtitle.append(f"grouped by: `{_local(row['groupedBy'])}`")
    if pd.notna(row.get("dataset")) and row.get("dataset"):
        subtitle.append(f"source: `{_local(row['dataset'])}`")
    if pd.notna(row.get("computedAt")) and row.get("computedAt"):
        subtitle.append(f"computed: {row['computedAt']}")

    with st.expander(f"{'📊' if kind == 'Set' else '🗂️'} **{title}** ({kind})"):
        st.caption(" · ".join(subtitle))

        stats = set_statistics(client, coll)
        if stats.empty:
            st.info("No statistics recorded for this collection.")
        else:
            wide = _stats_table(stats)
            if kind == "GroupedSet":
                st.dataframe(
                    wide.drop(columns=["set"]).rename(columns={"groupKey": "group"}),
                    use_container_width=True, hide_index=True)
                # One bar per group for the headline numeric statistic.
                for metric in ("mean", "count"):
                    if metric in wide.columns:
                        chart = wide[["groupKey", metric]].dropna()
                        chart[metric] = pd.to_numeric(chart[metric], errors="coerce")
                        chart = chart.dropna().set_index("groupKey")
                        if not chart.empty:
                            st.caption(f"{metric} per group")
                            st.bar_chart(chart)
                        break
            else:
                st.dataframe(wide.drop(columns=["set", "groupKey"]),
                             use_container_width=True, hide_index=True)
                st.caption(f"members: {member_count(client, coll)}")

        bins = set_bins(client, coll)
        if not bins.empty and kind == "Set":
            bins = bins.sort_values(["lower", "binLabel"], na_position="last")
            chart = bins[["binLabel", "frequency"]].copy()
            chart["frequency"] = pd.to_numeric(chart["frequency"], errors="coerce")
            st.caption("distribution")
            st.bar_chart(chart.set_index("binLabel"))

        c1, c2 = st.columns(2)
        if c1.button("Recompute", key=f"recompute_{coll}"):
            st.session_state["collections_recompute"] = {
                "attr": str(row["attrType"]),
                "group": str(row["groupedBy"]) if pd.notna(row.get("groupedBy")) and row.get("groupedBy") else None,
                "dataset": str(row["dataset"]) if pd.notna(row.get("dataset")) and row.get("dataset") else None,
            }
            st.rerun()
        if c2.button("Delete", key=f"delete_{coll}"):
            delete_collection(client, coll)
            st.rerun()


def collections_explorer(client):
    st.header("📊 Collections")
    st.caption(
        "Analyse the workspace at dataset level: aggregate every value of an "
        "attribute type into a Set with descriptive statistics, or partition "
        "one attribute by another (group by). Collections are derived — they "
        "are recomputed from the replica and cleared whenever the data reloads.")

    if client is None:
        st.info("Open a workspace (with its triplestore connection) first.")
        return
    ws_id = _workspace_id()

    # A queued recompute from the collection card (button → rerun → here, so
    # the success/error message lands at the top of the page).
    pending = st.session_state.pop("collections_recompute", None)
    if pending:
        _materialize(client, ws_id, pending["attr"], pending["group"],
                     pending["dataset"])

    # ── Builder ──────────────────────────────────────────────────────────
    attr_types = workspace_attribute_types(client)
    if attr_types.empty:
        st.warning("No attribute instances found in this workspace — build or "
                   "load a replica first.")
        return

    options = attr_types["attrType"].tolist()

    def fmt(iri):
        row = attr_types[attr_types["attrType"] == iri].iloc[0]
        n = row["instanceCount"]
        return f"{_local(iri)} ({n} values)"

    st.subheader("Build a collection")
    c1, c2 = st.columns(2)
    target = c1.selectbox("Attribute type", options, format_func=fmt,
                          key="collections_target")
    group_on = c2.checkbox("Group by a second attribute", key="collections_group_toggle")
    grouping = None
    if group_on:
        grouping = c2.selectbox(
            "Grouping attribute", [o for o in options if o != target],
            format_func=fmt, key="collections_grouping",
            help="Must be categorical (or a boolean/string value) — grouping by "
                 "raw continuous values is rejected.")

    datasets = workspace_datasets(client)
    dataset = None
    if not datasets.empty:
        ds_options = [None] + datasets["dataset"].tolist()

        def ds_fmt(iri):
            if iri is None:
                return "whole workspace replica"
            row = datasets[datasets["dataset"] == iri].iloc[0]
            label = row["label"] if pd.notna(row["label"]) and row["label"] else _local(iri)
            return f"{label} ({row['componentCount']} components)"

        dataset = st.selectbox("Restrict to data source", ds_options,
                               format_func=ds_fmt, key="collections_dataset")

    if st.button("Materialize", type="primary", key="collections_materialize"):
        _materialize(client, ws_id, target, grouping, dataset)

    # ── Existing collections ─────────────────────────────────────────────
    st.subheader("Materialized collections")
    existing = list_collections(client)
    if existing.empty:
        st.info("Nothing materialized yet — build one above.")
        return
    for _, row in existing.iterrows():
        _render_collection(client, row)


def _materialize(client, ws_id, target, grouping, dataset):
    try:
        with st.spinner("Computing statistics and writing the collection…"):
            if grouping:
                iri = materialize_grouped_set(client, ws_id, target, grouping,
                                              dataset)
            else:
                iri = materialize_set(client, ws_id, target, dataset)
        st.success(f"Materialized `{_local(iri)}` into the collections graph.")
    except CollectionError as e:
        st.error(f"Cannot materialize: {e}")
    except Exception as e:
        st.error(f"Materialization failed: {e}")
