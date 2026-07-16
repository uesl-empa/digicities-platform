# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager client - Streamlit adapter for backend OntologyFunctions.

Previously this module also supported an HTTP "API mode" that talked to a
deployed Flask backend. That mode was removed as part of the open source
release: the platform now runs purely in integrated mode with direct
GraphDB + local/NextCloud storage access.

This file stays in ``components/`` because it surfaces per-call errors via
``st.error``. Pure logic lives in ``backend.ontology_manager``.
"""

import streamlit as st
from typing import List, Dict, Optional, Any, Tuple

from backend.ontology_manager import OntologyFunctions


class OntologyAPIClient:
    """Streamlit-aware adapter over ``OntologyFunctions`` (integrated mode only)."""

    def __init__(self,
                 storage=None,
                 workspace_id: Optional[str] = None,
                 graphdb_client=None,
                 ontology_dir: Optional[str] = None,
                 nextcloud_client=None,
                 nextcloud_global_client=None,
                 **_legacy_kwargs):
        """
        Args:
            storage: WorkspaceStorage for the active workspace (backend-agnostic
                file I/O — local, NextCloud, …). Preferred over ontology_dir.
            workspace_id: Workspace ID (reporting / local fallback).
            graphdb_client: GraphDBClient/UnifiedGraphDBClient instance.
            ontology_dir: Directory for ontology files (local fallback only).
            nextcloud_client / nextcloud_global_client: ignored (back-compat).
            **_legacy_kwargs: Silently accepted for backward compatibility.
        """
        self.workspace_id = workspace_id
        self.graphdb_client = graphdb_client

        try:
            self.functions = OntologyFunctions(
                storage=storage,
                workspace_id=workspace_id,
                graphdb_client=graphdb_client,
                ontology_dir=ontology_dir,
            )
        except Exception as e:
            error_msg = f"Failed to initialize OntologyFunctions: {e}"
            print(error_msg)
            try:
                st.error(f"❌ {error_msg}")
            except Exception:
                pass
            raise

    # =================== Mode accessors (kept for UI compatibility) ===================

    def get_mode(self) -> str:
        return "integrated"

    def is_integrated_mode(self) -> bool:
        return True

    def is_api_mode(self) -> bool:
        return False

    def is_nextcloud_mode(self) -> bool:
        return self.functions is not None and self.functions.use_nextcloud

    def get_workspace_info(self) -> Dict[str, Any]:
        if self.functions:
            return self.functions.get_workspace_info()
        return {"mode": "integrated", "error": "Functions not initialized"}

    # =================== Extension Management ===================

    def fetch_extensions(self) -> Optional[List[str]]:
        return self.functions.list_extension_files()

    def get_active_extension(self) -> Optional[Dict]:
        return self.functions.get_active_extension()

    def load_extension(self, extension_filename: str) -> bool:
        success, message = self.functions.load_extension_and_update(extension_filename)
        if not success:
            st.error(f"❌ {message}")
        return success

    # =================== Component Operations ===================

    def fetch_components(self, extension_filename: str) -> List[Dict]:
        return self.functions.explore_components(extension_filename)

    def fetch_component_range(self, extension_filename: str, class_uri: str) -> List[Dict]:
        return self.functions.get_component_range(extension_filename, class_uri)

    def add_component(self, extension_filename: str, new_component: str,
                      new_component_label: str, parent_component: str) -> bool:
        success, message = self.functions.add_component(
            extension_filename, new_component_label, parent_component
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def remove_component(self, extension_filename: str, component_uri: str) -> bool:
        success, message = self.functions.remove_component(extension_filename, component_uri)
        if not success:
            st.error(f"❌ {message}")
        return success

    def change_component_parent(self, extension_filename: str, component_uri: str,
                                new_parent_uri: str) -> bool:
        success, message = self.functions.change_component_parent(
            extension_filename, component_uri, new_parent_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    # =================== Attribute Operations ===================

    def fetch_attributes(self, extension_filename: str) -> List[Dict]:
        return self.functions.explore_attributes(extension_filename)

    def fetch_attributes_by_type(self, extension_filename: str, attr_type: str) -> List[Dict]:
        type_map = {
            "Simple Cost": "SimpleCost",
            "Unit-Based Cost": "UnitBasedCost",
            "Categorical": "Categorical",
            "CustomPhysicalRatio": "CustomPhysicalRatio",
            "Event": "Event",
            "SimpleValue": "SimpleValue"
        }
        internal_type = type_map.get(attr_type, attr_type)
        return self.functions.explore_attributes_by_type(extension_filename, internal_type)

    def fetch_qudt_units(self) -> List[str]:
        return self.functions.get_qudt_units()

    def fetch_temporal_precisions(self) -> List[Dict]:
        return self.functions.get_temporal_precisions()

    def add_attribute(self, extension_filename: str, attribute_type: str,
                      new_attribute: str, attribute_label: str, **kwargs) -> bool:
        success, message = self.functions.add_attribute(
            extension_filename, attribute_type, attribute_label,
            qudt_unit=kwargs.get('qudt_unit', ''),
            y_qudt_unit=kwargs.get('y_qudt_unit', ''),
            x_unit=kwargs.get('x_unit', ''),
            temporal_precision=kwargs.get('temporal_precision', ''),
            parent_property=kwargs.get('parent_property', '')
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def remove_attribute(self, extension_filename: str, attribute_uri: str) -> bool:
        success, message = self.functions.remove_attribute(extension_filename, attribute_uri)
        if not success:
            st.error(f"❌ {message}")
        return success

    def link_attribute(self, extension_filename: str, component: str, property_uri: str) -> bool:
        success, message = self.functions.link_attribute(
            extension_filename, component, property_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def remove_attribute_link(self, extension_filename: str, component_uri: str,
                              attribute_uri: str) -> bool:
        success, message = self.functions.remove_attribute_link(
            extension_filename, component_uri, attribute_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def get_component_attributes(self, extension_filename: str, component_uri: str) -> List[Dict]:
        return self.functions.get_component_attributes(extension_filename, component_uri)

    # =================== Property Operations ===================

    def fetch_properties(self, extension_filename: str) -> List[Dict]:
        return self.functions.explore_properties(extension_filename)

    # =================== Category Operations ===================

    def get_attribute_categories(self, extension_filename: str) -> List[Dict]:
        return self.functions.get_attribute_categories(extension_filename)

    def get_attribute_categories_for_attribute(self, extension_filename: str,
                                               attribute_uri: str) -> List[Dict]:
        return self.functions.get_attribute_categories_for_attribute(
            extension_filename, attribute_uri
        )

    def add_attribute_to_category(self, extension_filename: str, attribute_uri: str,
                                  category_uri: str) -> bool:
        success, message = self.functions.add_attribute_to_category(
            extension_filename, attribute_uri, category_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def remove_attribute_from_category(self, extension_filename: str,
                                       attribute_uri: str, category_uri: str) -> bool:
        success, message = self.functions.remove_attribute_from_category(
            extension_filename, attribute_uri, category_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    # =================== Named Individuals Operations ===================

    def get_categorical_attributes(self, extension_filename: str) -> List[Dict]:
        return self.functions.get_categorical_attributes(extension_filename)

    def get_named_individuals(self, extension_filename: str, attribute_uri: str) -> List[Dict]:
        return self.functions.get_named_individuals(extension_filename, attribute_uri)

    def add_named_individual(self, extension_filename: str, individual_label: str,
                             attribute_uri: str) -> bool:
        success, message = self.functions.add_named_individual(
            extension_filename, individual_label, attribute_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def remove_named_individual(self, extension_filename: str, individual_uri: str) -> bool:
        success, message = self.functions.remove_named_individual(
            extension_filename, individual_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    # =================== Mapping Operations ===================

    def fetch_mapping_inputs(self) -> List[str]:
        return self.functions.list_mapping_inputs()

    def fetch_mapping_classes(self, mapping_filename: str) -> List[Dict]:
        return self.functions.get_mapping_classes(mapping_filename)

    def fetch_mapping_properties(self, mapping_filename: str) -> List[Dict]:
        return self.functions.get_mapping_properties(mapping_filename)

    def map_component(self, chosen_component: str, linkage_relation: str,
                      mapping_class: str, mapping_filename: str) -> bool:
        success, message = self.functions.map_component(
            chosen_component, linkage_relation, mapping_class, mapping_filename
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def map_attribute(self, chosen_attribute: str, linkage_relation: str,
                      mapping_class: str, mapping_filename: str) -> bool:
        success, message = self.functions.map_attribute(
            chosen_attribute, linkage_relation, mapping_class, mapping_filename
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def map_property(self, chosen_property: str, linkage_relation: str,
                     mapping_property: str, mapping_filename: str) -> bool:
        success, message = self.functions.map_property(
            chosen_property, linkage_relation, mapping_property, mapping_filename
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    def get_property_mappings(self, mapping_filename: str) -> List[Dict]:
        return self.functions.get_property_mappings(mapping_filename)

    def remove_property_mapping(self, mapping_filename: str, subject_uri: str,
                                predicate_uri: str, object_uri: str) -> bool:
        success, message = self.functions.remove_property_mapping(
            mapping_filename, subject_uri, predicate_uri, object_uri
        )
        if not success:
            st.error(f"❌ {message}")
        return success

    # =================== GraphDB Operations ===================

    def get_export_info(self, extension_filename: str) -> Optional[Dict]:
        return self.functions.get_export_info(extension_filename)

    def get_export_ttl_content(self, extension_filename: str) -> Optional[str]:
        """Return the merged TTL content of the extension's export file (for download / upstream propose)."""
        return self.functions.get_export_ttl_content(extension_filename)

    def get_repositories(self) -> Optional[Dict]:
        if not self.functions or not self.functions.graphdb_client:
            return {"repositories": [], "error": "GraphDB client not configured"}

        try:
            repositories = self.functions.get_repositories_from_graphdb()
            return {"repositories": repositories, "count": len(repositories)}
        except Exception as e:
            st.error(f"❌ Error fetching repositories: {str(e)}")
            return {"repositories": [], "error": str(e)}

    def upload_to_graphdb(self, extension_filename: str, repository: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """Upload the ontology to GraphDB - repository auto-detected if not provided."""
        if not repository:
            repository = self.workspace_id

        if not self.functions or not self.functions.graphdb_client:
            return False, {"error": "GraphDB client not configured"}

        try:
            success, result_info = self.functions.upload_to_graphdb(
                extension_filename, repository
            )
            return success, result_info
        except Exception as e:
            return False, {"error": str(e)}
