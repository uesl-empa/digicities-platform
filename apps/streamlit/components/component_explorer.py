# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Enhanced Component Explorer for the Digicities Platform — Streamlit shell.

The data half (SPARQL fetching, attribute processing, curve parsing, unit and
currency mapping, provenance) lives in ``backend.explorer`` so the REST API can
use it without a Streamlit runtime. This module renders: the component picker,
the instance table, curve plots, source panels and debug tools. The moved names
are re-exported below, so existing ``from components.component_explorer import
X`` call sites keep working unchanged.
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    from_clause,
)

# Re-exports: the explorer's data pipeline, extracted to backend/explorer.
# Every name that used to be defined here stays importable from here.
from backend.explorer import (  # noqa: F401
    AttributeProcessor,
    CURVE_META_PREFIX,
    SOURCE_COLUMN,
    SOURCE_META_COLUMN,
    attach_sources,
    clean_unit,
    curve_axis_units,
    curve_columns,
    curve_data_is_reference,
    extract_property_name,
    extract_readable_instance_name,
    extract_uri_fragment,
    get_component_attributes_comprehensive,
    get_component_basic_properties,
    get_component_data_unified,
    get_component_instances,
    get_component_sources,
    get_component_types_with_instances,
    get_visible_columns,
    map_currency_uri_to_string,
    map_unit_uri_to_string,
    parse_curve_data,
    process_enhanced_component_data,
    summarize_sources,
)
from backend.explorer import provenance as _provenance


# =============================================================================
# VISUALIZATION FUNCTIONS
# =============================================================================

_PLOT_POINT_LIMIT = 5000        # above this, draw a line only and say so


def _curve_meta(df: pd.DataFrame, instance_id, curve_column: str) -> Optional[Dict]:
    col = f"{CURVE_META_PREFIX}{curve_column}"
    if col not in df.columns or instance_id not in df.index:
        return None
    meta = df.loc[instance_id, col]
    return meta if isinstance(meta, dict) else None


def visualize_curve(df: pd.DataFrame, instance_id, curve_column: str):
    """Plot one instance's curve, using the points parsed at load time."""
    try:
        meta = _curve_meta(df, instance_id, curve_column)
        if meta is None:
            st.error(f"No curve data recorded for '{curve_column}' on this instance.")
            return

        if meta.get('reference'):
            st.info(f"This curve points at an external file rather than holding its "
                    f"points inline:\n\n`{meta['reference']}`\n\nNothing to plot here — "
                    f"open the data product to see the series.")
            return

        points = meta.get('points') or []
        if not points:
            st.warning("This curve has no plottable points.")
            with st.expander("Show the raw value"):
                st.code(str(meta.get('raw', ''))[:2000])
            st.caption("A curve with units but no points usually means the source cell "
                       "used a number format the ingestion didn't recognise (a space "
                       "after the comma, a negative, or scientific notation).")
            return

        # Points are stored in source order and nothing guarantees ascending x, so an
        # unsorted curve would render as a zigzag. Sort a copy for the line.
        ordered = sorted(points, key=lambda p: p[0])
        x_values = [p[0] for p in ordered]
        y_values = [p[1] for p in ordered]

        x_unit, y_unit = meta.get('x_unit', ''), meta.get('y_unit', '')
        x_label = f"X [{x_unit}]" if x_unit else "X (no unit recorded)"
        y_label = f"{curve_column} [{y_unit}]" if y_unit else f"{curve_column} (no unit recorded)"

        downsampled = len(ordered) > _PLOT_POINT_LIMIT
        if downsampled:
            step = len(ordered) // _PLOT_POINT_LIMIT + 1
            x_plot, y_plot = x_values[::step], y_values[::step]
        else:
            x_plot, y_plot = x_values, y_values

        fig, ax = plt.subplots(figsize=(12, 6))
        if len(ordered) == 1:
            ax.plot(x_plot, y_plot, 'o', markersize=10, color='#1f77b4')
        elif downsampled:
            ax.plot(x_plot, y_plot, '-', linewidth=1.5, color='#1f77b4')
        else:
            ax.plot(x_plot, y_plot, 'o-', linewidth=2, markersize=4, color='#1f77b4')

        ax.set_title(f"{curve_column} — {instance_id}", fontsize=14, fontweight='bold')
        ax.set_xlabel(x_label, fontsize=12)
        ax.set_ylabel(y_label, fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=10)

        note = f'Points: {len(ordered)}' + (f' (showing {len(x_plot)})' if downsampled else '')
        ax.text(0.02, 0.98, note, transform=ax.transAxes, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)                       # Streamlit reruns leak figures otherwise

        if len(ordered) == 1:
            st.caption("A single point — there is no curve to draw through it.")
        if not x_unit or not y_unit:
            missing = " and ".join(a for a, u in (("X", x_unit), ("Y", y_unit)) if not u)
            st.caption(f"No {missing} unit recorded for this curve. That is expected for a "
                       f"dimensionless axis (a coefficient or ratio); otherwise the unit is "
                       f"missing from the source data.")

        with st.expander("📊 Curve statistics"):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Data points", len(ordered))
            col2.metric(f"X range{f' [{x_unit}]' if x_unit else ''}",
                        f"{min(x_values):g} – {max(x_values):g}")
            col3.metric(f"Y range{f' [{y_unit}]' if y_unit else ''}",
                        f"{min(y_values):g} – {max(y_values):g}")
            col4.metric("Y mean", f"{np.mean(y_values):g}")
            st.dataframe(pd.DataFrame(ordered, columns=[x_label, y_label]),
                         use_container_width=True, height=240)

    except Exception as e:
        st.error(f"Error visualizing curve: {e}")


def _session_storage():
    """The current workspace's storage handle, from Streamlit session state.

    ``backend.explorer.provenance`` takes the storage as a parameter (it must
    not know about session state); this is the Streamlit side of that seam.
    """
    return getattr(st.session_state.get('workspace_context'), 'storage', None)


def _resolve_workspace_file(ref: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """A path inside the current workspace's storage -> (path, text), or None."""
    return _provenance.resolve_workspace_file(ref, _session_storage())


SOURCE_OPENERS = (_resolve_workspace_file,)


def open_source(ref: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """First opener that can fetch this source's content, else None."""
    for opener in SOURCE_OPENERS:
        try:
            found = opener(ref)
        except Exception:
            found = None
        if found:
            return found
    return None


def _render_source(ref: Dict[str, Any], key: str):
    """One source: what it is, where it is, and its content if we can reach it."""
    bits = [f"**{ref['label']}**"]
    if ref.get('type'):
        bits.append(f"`{ref['type']}`")
    st.markdown(' · '.join(bits))
    if ref.get('url'):
        st.caption(f"📍 {ref['url']}")
    if ref.get('date'):
        st.caption(f"🗓 accessed {ref['date']}")
    if ref.get('comment'):
        st.caption(ref['comment'])

    if st.button("📄 View source data", key=f"view_source_{key}"):
        found = open_source(ref)
        if found and found[1]:
            name, text = found
            st.caption(f"`{name}`")
            st.code(text[:20000], language=None)
            if len(text) > 20000:
                st.caption(f"…truncated, {len(text):,} characters in total")
        elif found:
            st.info(f"`{found[0]}` is in this workspace but isn't a text file — open it "
                    f"from the workspace rather than here.")
        else:
            # Not a failure: an onboarded working folder or an external dataset is
            # not in the workspace, so the recorded location is all there is.
            st.info(f"This source isn't stored in the workspace, so there's nothing to "
                    f"open here. It is recorded as **{ref.get('type') or 'a source'}** at "
                    f"`{ref.get('url') or ref['label']}`.")


def display_source_data(df: pd.DataFrame, filtered_df: pd.DataFrame):
    """Per-instance provenance: where the record came from, and where any single
    value came from when that differs from the record."""
    with st.expander("🔎 Data sources", expanded=False):
        options = [i for i in filtered_df.index.tolist()
                   if isinstance(df.loc[i, SOURCE_META_COLUMN], dict)]
        if not options:
            st.info("None of the instances shown record a source.")
            return

        def _label(idx):
            for col in ('instance_id', 'label'):
                if col in df.columns and isinstance(df.loc[idx, col], str) and df.loc[idx, col]:
                    return df.loc[idx, col]
            return str(idx)

        selected = st.selectbox("Instance", options, format_func=_label,
                                key="source_instance_selector")
        entry = df.loc[selected, SOURCE_META_COLUMN]

        st.markdown("**This record came from**")
        if entry.get('instance'):
            for n, ref in enumerate(entry['instance']):
                _render_source(ref, f"{selected}_inst_{n}")
        else:
            st.caption("No source recorded for the record as a whole.")

        if entry.get('attributes'):
            st.markdown("**Individual values that came from somewhere else**")
            st.caption("An attribute appears here when its own source differs from the "
                       "record's — for example a specification copied down from a "
                       "catalogue entry held in another file.")
            rows = [{'Attribute': attr,
                     'Source': ', '.join(r['label'] for r in refs),
                     'Location': ', '.join(r['url'] for r in refs if r.get('url'))}
                    for attr, refs in sorted(entry['attributes'].items())]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def display_data_table(df: pd.DataFrame, component_type: str):
    """Enhanced data table display with better attribute handling"""
    if df.empty:
        st.info(f"No data found for {component_type}")
        return

    visible_columns = get_visible_columns(df)
    display_df = df[visible_columns] if visible_columns else df

    # Search functionality
    search_term = st.text_input("🔍 Search in table:", "")

    if search_term:
        mask = display_df.astype(str).apply(lambda x: x.str.contains(search_term, case=False)).any(axis=1)
        filtered_df = display_df[mask]
    else:
        filtered_df = display_df

    st.write(f"📊 Showing {len(filtered_df)} instances of {component_type}")

    # Identified from the attached metadata, not from the column name.
    curve_cols = [c for c in curve_columns(df) if c in filtered_df.columns]
    has_sources = SOURCE_META_COLUMN in df.columns

    toggles = st.columns(2)
    show_curves = toggles[0].checkbox("Show curve data in table", value=False)
    show_sources = toggles[1].checkbox(
        "Show data sources", value=False, disabled=not has_sources,
        help="Where each instance came from — the file, data product or dataset it was "
             "read from. Off by default so the table stays about the data itself."
        if has_sources else
        "This replica records no sources. They are written when a workspace is "
        "populated by the onboarding agent, or when a workbook cites its Reference sheet.")

    table_df = filtered_df
    if not show_curves and curve_cols:
        table_df = table_df.drop(columns=curve_cols)
        st.info(f"Hiding {len(curve_cols)} curve data columns. Enable 'Show curve data' to display them.")
    if not show_sources and SOURCE_COLUMN in table_df.columns:
        table_df = table_df.drop(columns=[SOURCE_COLUMN])

    table_event = st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"explorer_table_{component_type}",
    )

    # Inspect the selected instance in the Query Manager. The selection is
    # positional within table_df; the URI lives in the full df's hidden columns,
    # reachable because every derived frame shares the original index.
    selected_rows = getattr(getattr(table_event, "selection", None), "rows", None) or []
    if selected_rows and "URI" in df.columns:
        row_idx = table_df.index[selected_rows[0]]
        uri = df.loc[row_idx, "URI"]
        label = next((df.loc[row_idx, c] for c in ("instance_id", "label")
                      if c in df.columns and isinstance(df.loc[row_idx, c], str)
                      and df.loc[row_idx, c]), None)
        if isinstance(uri, str) and uri:
            display = label or uri.rsplit("/", 1)[-1]
            if st.button(f"🔍 Inspect '{display}' in the Query Manager",
                         help="Open the Query Manager with recommended queries "
                              "about this instance — its links, attributes, class "
                              "relatives, catalogue derivation and data sources."):
                st.session_state.inspected_instance = {
                    "uri": uri, "label": display, "component_type": component_type,
                }
                st.session_state.pending_module_switch = "Query Manager"
                # Arrive with the overview query already in the editor.
                try:
                    from backend.graphdb.queries import recommended_queries
                    st.session_state.pending_query_text = \
                        recommended_queries(uri)[0]["sparql"]
                except Exception:
                    pass
                st.rerun()

    # Download functionality
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv = filtered_df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"{component_type}_data_{timestamp}.csv",
        mime="text/csv",
        key='download_button'
    )

    # Where the data came from
    if has_sources and show_sources:
        display_source_data(df, filtered_df)

    # Curve visualization
    if curve_cols:
        with st.expander("📈 Curve Visualization", expanded=False):
            st.subheader("Visualize Curve Data")

            instance_options = filtered_df.index.tolist()
            if not instance_options:
                st.warning("No instances available to visualize")
                return

            # The index is positional after reset_index, so show the instance's name
            # and map back — a list of integers told the user nothing.
            def _instance_label(idx):
                for col in ('instance_id', 'label'):
                    if col in df.columns:
                        val = df.loc[idx, col]
                        if isinstance(val, str) and val:
                            return f"{val}"
                return str(idx)

            selected_instance = st.selectbox(
                "Select Instance",
                instance_options,
                format_func=_instance_label,
                key="viz_instance_selector"
            )

            selected_curve = st.selectbox(
                "Select Curve",
                curve_cols,
                key="viz_curve_selector"
            )

            # `df`, not `filtered_df`: the parsed points live in hidden columns that
            # get_visible_columns strips out of the display frame.
            if st.button("📊 Generate Visualization"):
                with st.spinner("Generating curve visualization..."):
                    visualize_curve(df, selected_instance, selected_curve)


# =============================================================================
# DEBUG FUNCTIONS - ADDED
# =============================================================================

def debug_component_structure(client):
    """Debug query to understand the component structure"""
    query = f"""
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

    SELECT DISTINCT ?instance ?type ?label ?hasAttribute
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?instance a ?type .
      ?type rdfs:subClassOf* dici_onto:Component .
      OPTIONAL {{ ?instance rdfs:label ?label }}
      OPTIONAL {{
        ?instance ?attrPredicate ?hasAttribute .
        ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
      }}
    }}
    ORDER BY ?type ?instance
    LIMIT 50
    """

    try:
        result = client.sparql_api_query(query, out_format="df")
        if result is not None and not result.empty:
            st.write("### 🔧 Component Structure Debug")
            st.dataframe(result)

            # Show summary
            types_count = result['type'].nunique() if 'type' in result.columns else 0
            instances_count = result['instance'].nunique() if 'instance' in result.columns else 0
            st.write(f"**Found:** {types_count} component types, {instances_count} instances")

        return result
    except Exception as e:
        st.error(f"Debug query failed: {e}")
        return None


def debug_attribute_structure(client, component_type_label: str):
    """Debug query to understand attribute structure for a specific component type"""
    query = f"""
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT DISTINCT ?instance ?attribute ?property ?value
    {from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{
      ?componentType rdfs:label "{component_type_label}" .
      ?instance a ?componentType .
      ?instance ?attrPredicate ?attribute .
      ?attrPredicate rdfs:subPropertyOf* dici_onto:hasAttribute .
      ?attribute ?property ?value .
    }}
    ORDER BY ?instance ?attribute ?property
    LIMIT 100
    """

    try:
        result = client.sparql_api_query(query, out_format="df")
        if result is not None and not result.empty:
            st.write(f"### 🔧 Attribute Structure Debug for {component_type_label}")
            st.dataframe(result)

            # Show summary
            instances_count = result['instance'].nunique() if 'instance' in result.columns else 0
            attributes_count = result['attribute'].nunique() if 'attribute' in result.columns else 0
            st.write(f"**Found:** {instances_count} instances, {attributes_count} attributes")

        return result
    except Exception as e:
        st.error(f"Debug query failed: {e}")
        return None


# =============================================================================
# MAIN COMPONENT EXPLORER FUNCTION - ENHANCED
# =============================================================================

def component_explorer(client):
    """Enhanced Component Explorer main function - FIXED VERSION"""
    st.header("🔍 Digital Replica Explorer")
    st.write("Browse and visualize component instances and their attribute values from your Digital Replica")

    if not client:
        st.error("❌ No Triplestore client available")
        return

    # Debug section - ENHANCED
    with st.expander("🛠 Debug Information", expanded=False):
        st.markdown("**Triplestore Client Status:**")
        if client:
            st.success(f"✅ Connected to repository: {getattr(client, 'selected_repo', 'Unknown')}")
            st.write(f"**Base URL:** {getattr(client, 'base_url', 'Unknown')}")
            st.write(f"**Auth Mode:** {getattr(client, 'auth_mode', 'Unknown')}")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔧 Test Connection"):
                try:
                    test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
                    result = client.sparql_api_query(test_query, out_format="response")
                    if result and result.status_code == 200:
                        st.success("✅ Connection test successful")
                    else:
                        st.error("❌ Connection test failed")
                except Exception as e:
                    st.error(f"❌ Connection test failed: {str(e)}")

        with col2:
            if st.button("🔍 Debug Component Structure"):
                debug_component_structure(client)

    # Get component types and create dropdown
    with st.spinner("Loading component types with instances..."):
        try:
            component_types_df = get_component_types_with_instances(client)

            if component_types_df.empty:
                st.warning("⚠️ No component types with instances found in the knowledge graph")
                st.info("💡 This could mean:")
                st.markdown("- No component instances are loaded in this repository")
                st.markdown("- The ontology structure is different than expected")
                st.markdown("- The component instances are not properly typed")

                if st.button("🔧 Debug All Types"):
                    debug_query = """
                    SELECT DISTINCT ?type (COUNT(?instance) as ?count) WHERE {
                        ?instance a ?type .
                    }
                    GROUP BY ?type
                    ORDER BY DESC(?count)
                    LIMIT 20
                    """
                    try:
                        debug_result = client.sparql_api_query(debug_query, out_format="df")
                        if debug_result is not None and not debug_result.empty:
                            st.write("**Found these types in the knowledge graph:**")
                            st.dataframe(debug_result)
                        else:
                            st.write("No types found in the knowledge graph")
                    except Exception as e:
                        st.error(f"Debug query failed: {e}")
                return

            st.success(f"✅ Found {len(component_types_df)} component types with instances")

            # Component selection
            def format_component_option(idx):
                row = component_types_df.iloc[idx]
                return f"{row['componentName']} ({row['instanceCount']} instances)"

            selected_idx = st.selectbox(
                "Select a Component Type:",
                options=range(len(component_types_df)),
                format_func=format_component_option,
                key='component_selector'
            )

            selected_component = component_types_df.iloc[selected_idx]['componentName']
            instance_count = component_types_df.iloc[selected_idx]['instanceCount']

        except Exception as e:
            st.error(f"❌ Error loading component types: {str(e)}")
            import traceback
            with st.expander("🔍 Error Details"):
                st.code(traceback.format_exc())
            return

    # Collections: the dataset-level aggregations materialized for this replica
    # (full-dataset sets, group-by subdivisions, per-source sets). Read-only
    # view of the derived <collections> graph; building/recomputing lives in
    # the Collections module. Never breaks the explorer if unavailable.
    selected_collection = None
    try:
        from backend.collections import list_collections
        from components.collections_explorer import (
            collection_option_label, render_collection_body)
        collections_df = list_collections(client)
        if collections_df is not None and not collections_df.empty:
            coll_options = [None] + list(range(len(collections_df)))

            def format_collection_option(idx):
                if idx is None:
                    return f"— {len(collections_df)} available —"
                return collection_option_label(collections_df.iloc[idx])

            coll_idx = st.selectbox(
                "Collections (dataset-level aggregations):",
                options=coll_options,
                format_func=format_collection_option,
                key='explorer_collection_selector',
                help="Derived sets and group-by statistics materialized from "
                     "this replica. Build or recompute them in the "
                     "Collections module.")
            if coll_idx is not None:
                selected_collection = collections_df.iloc[coll_idx]
        else:
            st.caption("📊 No collections materialized yet — build dataset-level "
                       "aggregations (sets, group-bys) in the **Collections** module.")
    except Exception as e:
        st.caption(f"Collections unavailable: {e}")

    if selected_collection is not None:
        name = str(selected_collection['collection']).rsplit('/', 1)[-1]
        st.markdown(f"### 📊 Collection: **{name}**")
        render_collection_body(client, selected_collection)
        st.divider()

    # Main content area
    if selected_component:
        st.markdown(f"### 📊 Data for: **{selected_component}**")
        st.caption(f"Found {instance_count} instances of this component type")

        # Add debug option for this specific component type
        if st.button(f"🔧 Debug {selected_component} Attributes"):
            debug_attribute_structure(client, selected_component)

        with st.spinner(f"Loading {selected_component} data..."):
            try:
                component_instances, component_attributes = get_component_data_unified(client, selected_component)

                if component_instances and component_attributes:
                    df = process_enhanced_component_data(component_instances, component_attributes)
                    # Provenance is a separate, optional query: a replica with no
                    # sources recorded must look exactly as it did before.
                    df = attach_sources(df, get_component_sources(client, selected_component))

                    if not df.empty:
                        # FIXED: Better indexing for display
                        if 'instance_id' in df.columns:
                            df.index = df['instance_id']
                        elif 'URI' in df.columns:
                            df.index = df['URI'].apply(lambda x: extract_readable_instance_name(x) if x else '')

                        display_data_table(df, selected_component)
                    else:
                        st.error("❌ Failed to process component data into table format")
                        st.info("💡 Try using the debug options above to understand the data structure")

                elif component_instances and not component_attributes:
                    st.warning(f"Found {len(component_instances)} instances but no attributes")
                    st.info("This might mean the instances don't have linked attributes or use a different attribute pattern")

                    # Show the instances we found
                    if st.checkbox("Show found instances"):
                        instances_df = pd.DataFrame([
                            {
                                'URI': inst.get('instance', {}).get('value', ''),
                                'Instance ID': extract_readable_instance_name(inst.get('instance', {}).get('value', '')),
                                'Label': inst.get('instanceLabel', {}).get('value', '') if 'instanceLabel' in inst else ''
                            }
                            for inst in component_instances
                        ])
                        st.dataframe(instances_df)

                else:
                    st.error(f"❌ No data found for {selected_component}")

            except Exception as e:
                st.error(f"❌ Error loading component data: {str(e)}")
                import traceback
                with st.expander("🔍 Error Details"):
                    st.code(traceback.format_exc())

        # Footer information
        with st.expander("ℹ️ About Enhanced Component Explorer"):
            st.markdown("""
            **Enhanced Component Explorer** explores actual component instances and their attributes from your knowledge graph.

            **FIXED Features:**
            - **Universal Namespace Support**: Works with any URI namespace pattern (e.g., `http://ait.ac.at/NMS_Enkplatz#`)
            - **Smart URI Processing**: Automatically extracts meaningful names from any URI format
            - **Generic Component Detection**: Finds any component type without hard-coding names
            - **Enhanced Debugging**: Built-in tools to understand your data structure

            **Supported Attribute Types:**
            - **Physical Attributes**: Value + unit (e.g., "67.0 Wh")
            - **Cost Attributes**: Value + currency (e.g., "40.0 CHF")
            - **Unit-Based Cost**: Value + unit + currency (e.g., "3.0 CHF/kWh")
            - **Categorical**: Category values (e.g., "Crystalline")
            - **Curve Data**: X/Y data points for plotting
            - **Dynamic/Time Series**: Live, historic, or future data references
            - **Geospatial**: Location-based attributes
            - **SimpleValue**: Basic value without units (e.g., "4.0")
            - **CustomPhysicalRatio**: Custom unit ratios (e.g., "5.0 kg/kW")

            **How it works:**
            1. Automatically discovers all component types in your knowledge graph
            2. Extracts readable names from any URI format
            3. Processes attributes based on their semantic types
            4. Displays data in an intuitive table format
            """)
