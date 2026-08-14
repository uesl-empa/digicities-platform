# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from pathlib import Path

# Import Nextcloud client for global folder access (legacy fallback)
from components.nextcloud_module import get_nextcloud_client


def _workspace_storage(workspace_id):
    """Return the WorkspaceStorage for the given workspace_id if the active
    session has one matching it. Otherwise None — callers fall back to the
    legacy NextCloud global path so existing NextCloud workspaces keep working.
    """
    try:
        ctx = st.session_state.get("workspace_context")
        if ctx is not None and ctx.id == workspace_id:
            return ctx.storage
        # Otherwise consult the registry directly.
        from backend.workspace import load_registry
        ctx = load_registry().by_id(workspace_id)
        return ctx.storage if ctx is not None else None
    except Exception:
        return None


def query_manager(client):
    """SPARQL Query Manager module function - now workspace-aware with global queries"""
    st.header("SPARQL Query Manager")

    # Get current workspace info
    workspace = st.session_state.current_workspace
    st.write(f"Create, edit, run and manage SPARQL queries for **{workspace['name']}**")

    # A query handed over by another module (the Explorer's "Inspect instance",
    # or this panel's own Load buttons). Widget state can only be set BEFORE the
    # editor widget exists in a run, so the text is parked in pending_query_text
    # and applied here.
    pending_query = st.session_state.pop("pending_query_text", None)
    if pending_query is not None:
        st.session_state.current_query = pending_query
        st.session_state.query_editor = pending_query
        # Behave like an unsaved new query, so the saved-query selector does not
        # clobber the loaded text on the next rerun.
        st.session_state.create_new_query = True

    # The Instance Inspector: recommended queries for the instance selected in
    # the Digital Replica Explorer (or picked out of earlier query results).
    # Without one, the workspace's own recommended queries are the landing set.
    if st.session_state.get("inspected_instance"):
        _render_instance_inspector(client, workspace)
    else:
        _render_workspace_recommendations(client, workspace)

    # DEBUG: Show connection details in terminal and UI
    debug_connection_info(client, workspace)

    # Initialize all session state variables if not present
    query_session_key = f"queries_{workspace['id']}"
    if query_session_key not in st.session_state:
        st.session_state[query_session_key] = load_saved_queries_from_global(workspace['id'])

    if 'create_new_query' not in st.session_state:
        st.session_state.create_new_query = False

    if 'confirm_save' not in st.session_state:
        st.session_state.confirm_save = False

    if 'confirm_overwrite' not in st.session_state:
        st.session_state.confirm_overwrite = False

    if 'current_query' not in st.session_state:
        workspace_queries = st.session_state[query_session_key]
        if workspace_queries:
            first_query = next(iter(workspace_queries))
            st.session_state.current_query = workspace_queries[first_query]
            st.session_state.current_query_name = first_query
        else:
            st.session_state.current_query = get_default_query_for_workspace(workspace)
            st.session_state.current_query_name = ""

    # Display workspace-specific query info
    with st.expander("📊 Workspace Query Info", expanded=False):
        workspace_queries = st.session_state[query_session_key]

        # Show detailed connection info
        graphdb_endpoint = getattr(client, 'GraphDB_url', 'Not available')
        repository = getattr(client, 'repository', 'Not available')

        st.markdown(f"""
        **Workspace:** {workspace['name']}
        **Workspace ID:** {workspace['id']}
        **Workspace Type:** {workspace.get('type', 'Unknown')}
        **Saved Queries:** {len(workspace_queries)}
        **Query Storage:** Global Nextcloud (`global/queries/{workspace['id']}/`)
        **Triplestore Endpoint:** {graphdb_endpoint}
        **Repository:** {repository}
        """)

    # Add new query button
    col1, col2 = st.columns([6, 1])
    with col2:
        if st.button("➕ New Query"):
            st.session_state.create_new_query = True
            st.session_state.current_query_name = ""
            st.session_state.current_query = get_default_query_for_workspace(workspace)
            st.rerun()

    with col1:
        workspace_queries = st.session_state[query_session_key]
        # If there are no queries, show a message
        if not workspace_queries and not st.session_state.create_new_query:
            st.info("No saved queries for this workspace. Click '➕ New Query' to create one.")

        # If we're not creating a new query and not in dialog mode, show the query selector
        elif not st.session_state.create_new_query and not st.session_state.confirm_save and not st.session_state.confirm_overwrite:
            # Create dropdown for query selection
            query_names = list(workspace_queries.keys())

            if query_names:  # Only show selector if there are queries
                selected_query_name = st.selectbox(
                    "Select a saved query:",
                    options=query_names,
                    key='query_selector'
                )

                # Load the selected query
                if selected_query_name:
                    st.session_state.current_query_name = selected_query_name
                    st.session_state.current_query = workspace_queries[selected_query_name]

        elif st.session_state.create_new_query and not st.session_state.confirm_save and not st.session_state.confirm_overwrite:
            # If creating a new query, show a header
            st.subheader("Create New Query")

    # Don't show the editor when in save/overwrite dialog modes
    if not st.session_state.confirm_save and not st.session_state.confirm_overwrite:
        # Edit query section
        with st.container():
            # Query editor
            st.subheader("Query Editor")
            query_text = st.text_area(
                "Edit SPARQL Query:",
                value=st.session_state.get('current_query', ""),
                height=250,
                key='query_editor',
                help=f"Writing queries for {workspace['name']} workspace"
            )
            st.session_state.current_query = query_text

            # Action buttons for the query
            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                if st.button("🚀 Run Query"):
                    if not query_text.strip():
                        st.error("Query cannot be empty")
                    else:
                        run_query(client, query_text, workspace)

            with col2:
                if st.button("💾 Save Query"):
                    if not query_text.strip():
                        st.error("Query cannot be empty")
                    else:
                        # Set state to trigger save dialog
                        st.session_state.confirm_save = True
                        st.rerun()

            with col3:
                # Add Update button that saves the current query back to its file
                if st.button("🔄 Update Query"):
                    if not query_text.strip():
                        st.error("Query cannot be empty")
                    elif st.session_state.create_new_query or not st.session_state.current_query_name:
                        st.error("You must save a new query before updating it")
                    else:
                        # Update the current query in global storage
                        success = update_query_in_global(workspace['id'], st.session_state.current_query_name, query_text)
                        if success:
                            st.session_state[query_session_key][st.session_state.current_query_name] = query_text
                            st.success(f"Query '{st.session_state.current_query_name}' updated successfully")
                        else:
                            st.error("Failed to update query in global storage")
                        st.rerun()

            with col4:
                if st.button("❌ Delete Query"):
                    workspace_queries = st.session_state[query_session_key]
                    if 'current_query_name' in st.session_state and st.session_state.current_query_name and not st.session_state.create_new_query:
                        success = delete_query_from_global(workspace['id'], st.session_state.current_query_name)
                        if success:
                            # Update the queries dictionary
                            workspace_queries.pop(st.session_state.current_query_name, None)

                            # Reset to a valid query if there are any left
                            if workspace_queries:
                                next_query = list(workspace_queries.keys())[0]
                                st.session_state.current_query_name = next_query
                                st.session_state.current_query = workspace_queries[next_query]
                            else:
                                st.session_state.current_query_name = ""
                                st.session_state.current_query = get_default_query_for_workspace(workspace)

                            st.success("Query deleted successfully")
                        else:
                            st.error("Failed to delete query from global storage")
                        st.rerun()
                    else:
                        st.info("Select a saved query to delete")

            with col5:
                if st.button("🚫 Cancel"):
                    st.session_state.create_new_query = False
                    workspace_queries = st.session_state[query_session_key]

                    # If there are queries, load the first one
                    if workspace_queries:
                        next_query = list(workspace_queries.keys())[0]
                        st.session_state.current_query_name = next_query
                        st.session_state.current_query = workspace_queries[next_query]

                    st.rerun()

    # Save query confirmation dialog
    if st.session_state.confirm_save:
        with st.form(key="save_query_form"):
            st.subheader("Save Query to Global Storage")

            # Pre-fill with current name if editing existing query
            default_name = st.session_state.current_query_name if not st.session_state.create_new_query else ""
            query_name = st.text_input(
                "Enter a name for this query:",
                value=default_name,
                key="save_query_name"
            )

            col1, col2 = st.columns(2)
            save_submitted = col1.form_submit_button("Save to Global")
            cancel_save = col2.form_submit_button("Cancel")

            if save_submitted:
                workspace_queries = st.session_state[query_session_key]
                if not query_name.strip():
                    st.error("Please enter a name for the query")
                    st.stop()

                # Check if query with this name already exists and it's not the same query being edited
                if query_name in workspace_queries and (
                        st.session_state.create_new_query or
                        query_name != st.session_state.current_query_name
                ):
                    # Set state to trigger overwrite confirmation
                    st.session_state.confirm_overwrite = True
                    st.session_state.temp_query_name = query_name
                    st.session_state.confirm_save = False
                    st.rerun()
                else:
                    # Save the query to global storage
                    query_text = st.session_state.current_query
                    success = save_query_to_global(workspace['id'], query_name, query_text)
                    if success:
                        st.session_state[query_session_key] = load_saved_queries_from_global(workspace['id'])
                        st.session_state.current_query_name = query_name
                        st.session_state.current_query = query_text
                        st.session_state.create_new_query = False
                        st.session_state.confirm_save = False
                        st.success(f"Query '{query_name}' saved successfully to global storage")
                    else:
                        st.error("Failed to save query to global storage")
                    st.rerun()

            if cancel_save:
                st.session_state.confirm_save = False
                st.rerun()

    # Overwrite confirmation dialog
    if st.session_state.confirm_overwrite:
        with st.form(key="overwrite_query_form"):
            st.subheader("Confirm Overwrite")
            st.warning(f"A query with the name '{st.session_state.temp_query_name}' already exists in {workspace['name']}. Do you want to overwrite it?")

            col1, col2 = st.columns(2)
            overwrite = col1.form_submit_button("Overwrite")
            cancel_overwrite = col2.form_submit_button("Cancel")

            if overwrite:
                # Save the query (overwriting) to global storage
                query_text = st.session_state.current_query
                success = save_query_to_global(workspace['id'], st.session_state.temp_query_name, query_text)
                if success:
                    query_session_key = f"queries_{workspace['id']}"
                    st.session_state[query_session_key] = load_saved_queries_from_global(workspace['id'])
                    st.session_state.current_query_name = st.session_state.temp_query_name
                    st.session_state.current_query = query_text
                    st.session_state.create_new_query = False
                    st.session_state.confirm_overwrite = False
                    st.success(f"Query '{st.session_state.temp_query_name}' updated successfully in global storage")
                else:
                    st.error("Failed to save query to global storage")
                st.rerun()

            if cancel_overwrite:
                st.session_state.confirm_overwrite = False
                st.session_state.confirm_save = True  # Go back to save dialog
                st.rerun()

    # Display query results area
    if 'query_results' in st.session_state:
        display_query_results(st.session_state.query_results, workspace)


def _render_instance_inspector(client, workspace):
    """Recommended queries for the instance handed over by the Explorer.

    Each recommendation is a plain SPARQL string built by the backend from the
    core ontology's rules (property hierarchies and class kinship) — loading one
    puts it in the ordinary editor, so it can be edited, run, and saved like any
    other query.
    """
    from backend.graphdb.queries import available_recommendations

    inspected = st.session_state.inspected_instance
    with st.container(border=True):
        head, clear = st.columns([6, 1])
        head.markdown(
            f"🔍 **Inspecting:** `{inspected.get('label', '?')}` "
            f"({inspected.get('component_type', 'instance')})\n\n"
            f"`{inspected.get('uri', '')}`")
        if clear.button("✖ Clear", key="inspector_clear",
                        help="Stop inspecting this instance"):
            st.session_state.pop("inspected_instance", None)
            st.rerun()

        try:
            # ASK-pre-flighted: recommendations whose pattern matches nothing in
            # this workspace are hidden rather than offered as dead ends.
            recs = available_recommendations(client, inspected["uri"])
        except (KeyError, ValueError) as exc:
            st.error(f"Cannot build queries for this instance: {exc}")
            return
        if not recs:
            st.info("The graph records nothing about this instance.")
            return

        _render_recommendation_picker(
            client, workspace, recs, key_prefix="inspector",
            label="Recommended queries for this instance")


def _render_workspace_recommendations(client, workspace):
    """The Query Manager's landing set: recommended queries for the workspace as
    a whole — all components, links, attribute values, scenarios, data sources,
    catalogue entries. ASK-pre-flighted like the instance recommendations, so a
    workspace without scenarios simply doesn't offer the scenarios query."""
    from backend.graphdb.queries import available_workspace_queries

    with st.expander("💡 Recommended queries for this workspace", expanded=True):
        recs = available_workspace_queries(client)
        if not recs:
            st.info("The workspace graph is empty — build a replica first.")
            return
        _render_recommendation_picker(
            client, workspace, recs, key_prefix="ws_rec",
            label="Recommended queries")


def _render_recommendation_picker(client, workspace, recs, key_prefix, label):
    """One recommendation picker: selectbox + description + Load / Load & run.
    Loading puts the SPARQL in the ordinary editor via pending_query_text, so it
    can be edited, run and saved like any hand-written query."""
    by_name = {r["name"]: r for r in recs}
    choice = st.selectbox(
        label, list(by_name), key=f"{key_prefix}_recommendation",
        help="Derived from the core ontology's rules — property hierarchies "
             "(linksComponent, hasAttribute, derivedFromCatalogue, "
             "prov:wasDerivedFrom) and the class hierarchy — so they work for "
             "any workspace's classes.")
    rec = by_name[choice]
    st.caption(rec["description"])

    load, run_now = st.columns(2)
    if load.button("📝 Load into editor", key=f"{key_prefix}_load"):
        st.session_state.pending_query_text = rec["sparql"]
        st.rerun()
    if run_now.button("🚀 Load & run", key=f"{key_prefix}_load_run"):
        st.session_state.pending_query_text = rec["sparql"]
        run_query(client, rec["sparql"], workspace)
        st.rerun()


def debug_connection_info(client, workspace):
    """Print debugging information about the GraphDB connection to terminal and optionally display in UI"""
    print("=" * 60)
    print("GRAPHDB CONNECTION DEBUG INFO")
    print("=" * 60)
    print(f"Workspace Name: {workspace.get('name', 'Unknown')}")
    print(f"Workspace ID: {workspace.get('id', 'Unknown')}")
    print(f"Workspace Type: {workspace.get('type', 'Unknown')}")

    # Check client attributes
    if hasattr(client, 'GraphDB_url'):
        print(f"GraphDB URL: {client.GraphDB_url}")
    else:
        print("GraphDB URL: NOT SET")

    if hasattr(client, 'repository'):
        print(f"Repository: {client.repository}")
    else:
        print("Repository: NOT SET")

    if hasattr(client, 'access_token'):
        print(f"Access Token: {'SET' if client.access_token else 'NOT SET'}")
    else:
        print("Access Token: NOT AVAILABLE")

    # Check available methods on client
    client_methods = [method for method in dir(client) if not method.startswith('_')]
    print(f"Available client methods: {client_methods}")

    print("=" * 60)


def get_default_query_for_workspace(workspace):
    """Get a default query template based on workspace type"""
    workspace_type = workspace.get('type', 'Unknown')

    if workspace_type == "Renewable Energy":
        return """PREFIX dici_onto: <https://digicities.info/ontology#>
SELECT ?turbine ?powerOutput ?efficiency WHERE {
  ?turbine a dici_onto:WindTurbine .
  ?turbine dici_onto:hasPowerOutput ?powerOutput .
  ?turbine dici_onto:hasEfficiency ?efficiency .
} LIMIT 100"""

    elif workspace_type == "Municipal Infrastructure":
        return """PREFIX dici_onto: <https://digicities.info/ontology#>
SELECT ?infrastructure ?energyConsumption ?location WHERE {
  ?infrastructure a dici_onto:Infrastructure .
  ?infrastructure dici_onto:hasEnergyConsumption ?energyConsumption .
  ?infrastructure dici_onto:hasLocation ?location .
} LIMIT 100"""

    elif workspace_type == "Building Management":
        return """PREFIX dici_onto: <https://digicities.info/ontology#>
SELECT ?building ?room ?temperature ?occupancy WHERE {
  ?building a dici_onto:Building .
  ?building dici_onto:hasRoom ?room .
  ?room dici_onto:hasTemperature ?temperature .
  ?room dici_onto:hasOccupancy ?occupancy .
} LIMIT 100"""

    else:
        return """PREFIX dici_onto: <https://digicities.info/ontology#>
SELECT * WHERE {
  # Enter your workspace-specific query here
  ?s ?p ?o .
} LIMIT 100"""


def run_query(client, query, workspace):
    """Execute SPARQL query and store results - Compatible with full GraphDBClient"""
    try:
        # Debug: Print what we're about to do
        print(f"EXECUTING QUERY ON:")
        print(f"  Workspace: {workspace['name']} (ID: {workspace['id']})")
        print(f"  Repository: {getattr(client, 'repository', 'UNKNOWN')}")
        print(f"  GraphDB URL: {getattr(client, 'GraphDB_url', 'UNKNOWN')}")
        print(f"  Query length: {len(query)} characters")
        print(f"  First 200 chars of query: {query[:200]}...")

        with st.spinner(f"Executing query on {workspace['name']}..."):
            # Use the full GraphDBClient method with out_format parameter
            raw_response = client.sparql_api_query(query=query, out_format="response")

            # Store the raw response for processing
            st.session_state.query_results = raw_response
            st.success(f"Query executed successfully on {workspace['name']}!")

            # Debug: Print success info
            print(f"QUERY EXECUTION SUCCESS:")
            print(f"  Response type: {type(raw_response)}")
            print(f"  Response status: {getattr(raw_response, 'status_code', 'N/A')}")

    except Exception as e:
        error_msg = f"Error executing query on {workspace['name']}: {str(e)}"
        st.error(error_msg)

        # Debug: Print detailed error info
        print(f"QUERY EXECUTION ERROR:")
        print(f"  Workspace: {workspace['name']} (ID: {workspace['id']})")
        print(f"  Error type: {type(e).__name__}")
        print(f"  Error message: {str(e)}")
        print(f"  Repository: {getattr(client, 'repository', 'UNKNOWN')}")
        print(f"  GraphDB URL: {getattr(client, 'GraphDB_url', 'UNKNOWN')}")

        st.session_state.query_results = None


def display_query_results(raw_response, workspace):
    """Display query results in a table with workspace context"""
    if raw_response is None:
        return

    st.subheader(f"Query Results - {workspace['name']}")

    try:
        # Parse the JSON response
        if hasattr(raw_response, 'text'):
            # If raw_response is a requests.Response object
            import json
            results = json.loads(raw_response.text)
        elif isinstance(raw_response, dict):
            # If it's already a dictionary
            results = raw_response
        else:
            st.error("Unexpected response format")
            return

        # Check if we have results
        if not results or 'results' not in results or 'bindings' not in results['results'] or len(results['results']['bindings']) == 0:
            st.info(f"No results returned from the query on {workspace['name']}")
            return

        # Get the variable names from the head section
        variables = results['head']['vars']

        # Process the bindings into a DataFrame
        processed_results = []
        for binding in results['results']['bindings']:
            row = {}
            for var in variables:
                if var in binding:
                    # Extract the value
                    row[var] = binding[var]['value']
                else:
                    row[var] = None
            processed_results.append(row)

        # Convert to DataFrame
        df = pd.DataFrame(processed_results)

        # Display row count
        st.write(f"Found {len(df)} results from {workspace['name']}")

        # Namespace handling in a collapsible section
        with st.expander("Namespace Handling Settings", expanded=False):
            # Load workspace-specific namespaces from global storage
            namespace_session_key = f'namespaces_{workspace["id"]}'
            if namespace_session_key not in st.session_state:
                st.session_state[namespace_session_key] = load_namespaces_from_global(workspace['id'])

            # Namespace settings
            namespaces_text = ""
            for prefix, uri in st.session_state[namespace_session_key].items():
                namespaces_text += f"{prefix}: {uri}\n"

            new_namespaces_text = st.text_area(
                f"Namespaces for {workspace['name']} (prefix: URI)",
                value=namespaces_text,
                height=150,
                key=f"namespaces_editor_{workspace['id']}"
            )

            # Parse new namespaces
            if new_namespaces_text != namespaces_text:
                new_namespaces = {}
                for line in new_namespaces_text.strip().split("\n"):
                    if ":" in line:
                        prefix, uri = line.split(":", 1)
                        new_namespaces[prefix.strip()] = uri.strip()

                # Save namespaces to global storage
                st.session_state[namespace_session_key] = new_namespaces
                save_namespaces_to_global(workspace['id'], new_namespaces)

            # Display options
            col1, col2 = st.columns(2)
            with col1:
                use_namespace_replacement = st.checkbox("Replace Namespaces", value=True, key=f"ns_replace_{workspace['id']}")
            with col2:
                extract_last_path = st.checkbox("Extract Last Path Element", value=False, key=f"ns_extract_{workspace['id']}")

        # Apply transformations if needed
        if 'use_namespace_replacement' not in locals():
            use_namespace_replacement = True
            extract_last_path = False

        display_df = df.copy()

        if use_namespace_replacement or extract_last_path:
            for col in display_df.columns:
                # Only process columns that contain URI values
                if display_df[col].dtype == 'object':  # String columns
                    if use_namespace_replacement:
                        # Replace namespaces
                        for prefix, uri in st.session_state[namespace_session_key].items():
                            display_df[col] = display_df[col].str.replace(uri, f"{prefix}:", regex=False)

                    if extract_last_path:
                        # Extract last path element
                        display_df[col] = display_df[col].apply(
                            lambda x: x.split('/')[-1].split('#')[-1] if isinstance(x, str) else x
                        )

        # Show the data table
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        # Buttons for data download
        col1, col2 = st.columns(2)
        with col1:
            # Add download button for transformed data
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv = display_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Formatted Results as CSV",
                data=csv,
                file_name=f"{workspace['id']}_query_results_{timestamp}.csv",
                mime="text/csv",
                key=f'download_results_button_{workspace["id"]}'
            )

        with col2:
            # Add download button for raw data
            raw_csv = df.to_csv(index=False)
            st.download_button(
                label="📥 Download Raw Results as CSV",
                data=raw_csv,
                file_name=f"{workspace['id']}_query_results_raw_{timestamp}.csv",
                mime="text/csv",
                key=f'download_raw_results_button_{workspace["id"]}'
            )

        # Any URI in the results can become the subject of a follow-up query.
        _render_explore_results(df)

        # Expandable section with raw JSON
        with st.expander("Raw JSON Response", expanded=False):
            st.json(results)
    except Exception as e:
        st.error(f"Error displaying results: {str(e)}")
        st.exception(e)


def _render_explore_results(df):
    """Follow-up exploration: pick any URI out of the results and inspect it as
    the subject of the recommended queries — components, classes, references,
    whatever the query returned. Works on the RAW frame, so the full URIs are
    intact regardless of the namespace display settings."""
    import re as _re

    uris, seen = [], set()
    for col in df.columns:
        for v in df[col]:
            if isinstance(v, str) and v.startswith(("http://", "https://")) and v not in seen:
                seen.add(v)
                uris.append(v)
    if not uris:
        return

    st.subheader("🔍 Explore a result")
    st.caption("Turn any URI from the results into the subject of a follow-up "
               "query — the recommended queries then target it.")
    if len(uris) > 500:
        st.caption(f"Showing the first 500 of {len(uris)} distinct URIs.")
        uris = uris[:500]

    def _short(u):
        tail = "/".join(u.rsplit("/", 2)[-2:])
        return tail if len(tail) <= 80 else "…" + tail[-79:]

    choice = st.selectbox("URI from the results:", uris, format_func=_short,
                          key="explore_result_uri")
    if st.button("🔍 Inspect as subject", key="explore_result_go"):
        from backend.graphdb.queries import recommended_queries
        st.session_state.inspected_instance = {
            "uri": choice,
            "label": _re.split(r"[#/]", choice.rstrip("#/"))[-1],
            "component_type": "query result",
        }
        try:
            st.session_state.pending_query_text = recommended_queries(choice)[0]["sparql"]
        except ValueError:
            pass
        st.rerun()


# ==================== GLOBAL STORAGE FUNCTIONS ====================

def load_saved_queries_from_global(workspace_id):
    """Load saved queries for the workspace.

    Priority:
    1. The workspace's own `queries/*.sparql` (via WorkspaceStorage) — works for
       local and NextCloud workspaces, the registered location.
    2. Legacy: NextCloud `global/queries/{workspace_id}/*.sparql` — pre-v0.2
       layout, retained so existing NextCloud users aren't broken.
    """
    queries = {}

    storage = _workspace_storage(workspace_id)
    if storage is not None:
        try:
            for rel_path in storage.glob("queries/*.sparql"):
                query_name = rel_path.rsplit("/", 1)[-1][:-len(".sparql")]
                try:
                    queries[query_name] = storage.read_text(rel_path)
                except Exception as e:
                    print(f"Error reading {rel_path}: {e}")
        except Exception as e:
            print(f"Error scanning workspace queries for {workspace_id}: {e}")

    # Legacy NextCloud global queries — included as supplement (not replaced),
    # so users migrating from NextCloud see their queries even before they
    # move them under the workspace.
    if not queries:
        try:
            global_client = get_nextcloud_client("global")
            files = global_client.list_files()
            query_files = [f for f in files if f['name'].startswith(f"queries/{workspace_id}/") and f['name'].endswith('.sparql')]
            for file_info in query_files:
                filename = file_info['name']
                query_name = filename.split('/')[-1].replace('.sparql', '')
                try:
                    queries[query_name] = global_client.download_text_file(filename)
                except Exception as e:
                    print(f"Error loading legacy query {query_name}: {e}")
        except Exception as e:
            print(f"NextCloud unavailable for {workspace_id} (fine in local mode): {e}")

    # Seed a default if nothing exists anywhere
    if not queries:
        workspace_info = {'type': 'Unknown'}
        if storage is not None:
            try:
                if storage.exists("workspace_meta/metadata.json"):
                    workspace_info = json.loads(storage.read_text("workspace_meta/metadata.json"))
            except Exception:
                pass
        default_query = get_default_query_for_workspace(workspace_info)
        default_name = f"Default {workspace_info.get('type', 'Query')}"
        save_query_to_global(workspace_id, default_name, default_query)
        queries[default_name] = default_query

    return queries


def save_query_to_global(workspace_id, query_name, query_content):
    """Save a query. Writes to the workspace's queries/ if registered, else
    falls back to NextCloud's legacy global/queries/{workspace_id}/."""
    storage = _workspace_storage(workspace_id)
    if storage is not None:
        try:
            storage.write_text(f"queries/{query_name}.sparql", query_content)
            return True
        except Exception as e:
            print(f"Error saving {query_name} to workspace storage: {e}")
            return False
    try:
        global_client = get_nextcloud_client("global")
        return global_client.upload_file(f"queries/{workspace_id}/{query_name}.sparql", query_content)
    except Exception as e:
        print(f"Error saving {query_name} to NextCloud: {e}")
        return False


def update_query_in_global(workspace_id, query_name, query_content):
    """Update an existing query."""
    return save_query_to_global(workspace_id, query_name, query_content)


def delete_query_from_global(workspace_id, query_name):
    """Delete a query from the workspace's queries/ (or NextCloud legacy fallback)."""
    storage = _workspace_storage(workspace_id)
    if storage is not None:
        try:
            storage.delete(f"queries/{query_name}.sparql")
            return True
        except Exception as e:
            print(f"Error deleting {query_name} from workspace storage: {e}")
            return False
    try:
        global_client = get_nextcloud_client("global")
        return global_client.delete_file(f"queries/{workspace_id}/{query_name}.sparql")
    except Exception as e:
        print(f"Error deleting {query_name} from NextCloud: {e}")
        return False


def load_namespaces_from_global(workspace_id):
    """Load namespaces from the workspace's queries/namespaces.txt, falling back
    to NextCloud, then to defaults."""
    storage = _workspace_storage(workspace_id)
    if storage is not None:
        try:
            if storage.exists("queries/namespaces.txt"):
                content = storage.read_text("queries/namespaces.txt")
                namespaces = {}
                for line in content.strip().split("\n"):
                    if ":" in line:
                        prefix, uri = line.split(":", 1)
                        namespaces[prefix.strip()] = uri.strip()
                if namespaces:
                    return namespaces
        except Exception as e:
            print(f"Error loading namespaces from workspace storage: {e}")

    try:
        global_client = get_nextcloud_client("global")
        namespace_content = global_client.download_text_file(f"queries/{workspace_id}/namespaces.txt")
        namespaces = {}
        for line in namespace_content.strip().split("\n"):
            if ":" in line:
                prefix, uri = line.split(":", 1)
                namespaces[prefix.strip()] = uri.strip()
        return namespaces
    except Exception:
        return get_default_namespaces_for_workspace({'id': workspace_id})


def save_namespaces_to_global(workspace_id, namespaces):
    """Save namespaces to the workspace's queries/namespaces.txt."""
    namespace_content = "".join(f"{prefix}: {uri}\n" for prefix, uri in namespaces.items())
    storage = _workspace_storage(workspace_id)
    if storage is not None:
        try:
            storage.write_text("queries/namespaces.txt", namespace_content)
            return True
        except Exception as e:
            print(f"Error saving namespaces to workspace storage: {e}")
            return False
    try:
        global_client = get_nextcloud_client("global")
        global_client.upload_file(f"queries/{workspace_id}/namespaces.txt", namespace_content)
        return True
    except Exception as e:
        print(f"Error saving namespaces to NextCloud: {e}")
        return False


def get_default_namespaces_for_workspace(workspace):
    """Get default namespaces based on workspace"""
    base_namespaces = {
        "dici_onto": "https://digicities.info/ontology#",
        "unit": "http://qudt.org/vocab/unit/",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#"
    }

    workspace_id = workspace.get('id', 'default')

    # Add workspace-specific project namespace
    base_namespaces["prj"] = f"https://digicities.info/proj/{workspace_id}/"

    return base_namespaces