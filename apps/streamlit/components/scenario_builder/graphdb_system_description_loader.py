# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/scenario_builder/graphdb_system_description_loader.py
"""
GraphDB System Description Loader
Queries the system_description named graph for physical component links
using dici_onto:linksComponent subproperties to assist scenario building
"""
import streamlit as st
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd

# Import GraphDB client
try:
    from components.graphdb import get_or_refresh_graphdb_client

    GRAPHDB_AVAILABLE = True
except ImportError:
    GRAPHDB_AVAILABLE = False

from backend.graphdb.queries import system_description as gq_sysdesc


class SystemDescriptionLinkQuery:
    """
    Query system description graph for component links using dici_onto:linksComponent
    """

    def __init__(self, workspace_id: str = None):
        """Initialize with workspace context"""
        self.workspace_id = workspace_id or st.session_state.get('current_workspace', {}).get('id')
        self.client = None

        if GRAPHDB_AVAILABLE and self.workspace_id:
            try:
                self.client = get_or_refresh_graphdb_client(self.workspace_id)
            except Exception as e:
                st.warning(f"Could not connect to Triplestore: {e}")

    def query_all_component_links(self) -> List[Dict[str, Any]]:
        """Query all component links from system_description graph"""
        if not self.client:
            st.error("Triplestore client not available")
            return []

        links = self._query_direct_located_in()
        if links:
            return links

        links = self._query_with_subproperty_reasoning()
        if links:
            return links

        links = self._query_all_component_relationships()
        return links

    def _query_direct_located_in(self) -> List[Dict[str, Any]]:
        """Direct query for locatedIn relationships
        (via backend.graphdb.queries.system_description)."""
        try:
            result = gq_sysdesc.query_direct_located_in(self.client)
            if result is None or result.empty:
                return []

            links = []
            for _, row in result.iterrows():
                link = {
                    'source_uri': row['source'],
                    'source_type': self._extract_type_name(row['sourceType']),
                    'link_property': 'locatedIn',
                    'target_uri': row['target'],
                    'target_type': self._extract_type_name(row['targetType']),
                    'source_label': self._extract_fragment(row['source']),
                    'target_label': self._extract_fragment(row['target'])
                }
                links.append(link)
            return links
        except Exception as e:
            st.warning(f"Direct locatedIn query failed: {e}")
            return []

    def _query_with_subproperty_reasoning(self) -> List[Dict[str, Any]]:
        """Query with subproperty reasoning
        (via backend.graphdb.queries.system_description)."""
        try:
            result = gq_sysdesc.query_links_with_subproperty(self.client)
            if result is None or result.empty:
                return []
            return self._process_query_results(result)
        except Exception as e:
            st.warning(f"Subproperty query failed: {e}")
            return []

    def _query_all_component_relationships(self) -> List[Dict[str, Any]]:
        """Broad query for component relationships
        (via backend.graphdb.queries.system_description)."""
        try:
            result = gq_sysdesc.query_all_component_relationships(self.client)
            if result is None or result.empty:
                return []
            return self._process_query_results(result)
        except Exception as e:
            st.error(f"Broad query failed: {e}")
            return []

    def _process_query_results(self, result: pd.DataFrame) -> List[Dict[str, Any]]:
        """Process SPARQL results"""
        links = []
        for _, row in result.iterrows():
            link = {
                'source_uri': row['source'],
                'source_type': self._extract_type_name(row['sourceType']),
                'link_property': self._extract_property_name(row['linkProperty']),
                'target_uri': row['target'],
                'target_type': self._extract_type_name(row['targetType']),
                'source_label': self._extract_fragment(row['source']),
                'target_label': self._extract_fragment(row['target'])
            }
            links.append(link)
        return links

    def match_links_to_requirements(self, discovered_links: List[Dict[str, Any]],
                                    requirements: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Match discovered links to YAML requirements"""
        matched_links = {}

        for req_pattern in requirements:
            parsed = self._parse_requirement_pattern(req_pattern)
            if not parsed['valid']:
                continue

            source_type = parsed['source_type']
            target_type = parsed['target_type']

            # Check both directions since locatedIn is reversed
            matches = [
                link for link in discovered_links
                if link['source_type'] == target_type and link['target_type'] == source_type
            ]

            if not matches:
                matches = [
                    link for link in discovered_links
                    if link['source_type'] == source_type and link['target_type'] == target_type
                ]

            if matches:
                matched_links[req_pattern] = matches

        return matched_links

    def _parse_requirement_pattern(self, pattern: str) -> Dict[str, str]:
        """Parse CL.Source.Target pattern"""
        parts = pattern.split('.')
        if len(parts) < 3:
            return {'source_type': 'Unknown', 'target_type': 'Unknown', 'valid': False}
        return {'source_type': parts[1], 'target_type': parts[2], 'valid': True}

    def _extract_fragment(self, uri: str) -> str:
        """Extract last part of URI"""
        if '#' in uri:
            return uri.split('#')[-1]
        elif '/' in uri:
            return uri.split('/')[-1]
        return uri

    def _extract_type_name(self, uri: str) -> str:
        """Extract type name from URI"""
        return self._extract_fragment(uri)

    def _extract_property_name(self, uri: str) -> str:
        """Extract property name from URI"""
        return self._extract_fragment(uri)


def get_system_description_loader() -> Optional[SystemDescriptionLinkQuery]:
    """Get system description loader for current workspace"""
    current_workspace = st.session_state.get('current_workspace')
    if not current_workspace:
        return None
    return SystemDescriptionLinkQuery(current_workspace['id'])


def get_system_description_links_for_requirement(req_pattern: str) -> List[Dict[str, Any]]:
    """Get system description links for a specific requirement pattern"""
    loader = get_system_description_loader()
    if not loader:
        return []

    all_links = loader.query_all_component_links()
    if not all_links:
        return []

    matched = loader.match_links_to_requirements(all_links, [req_pattern])
    return matched.get(req_pattern, [])