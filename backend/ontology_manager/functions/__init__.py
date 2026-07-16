# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Functions - Main Module
File: components/ontology_manager/functions/__init__.py

Main OntologyFunctions class that combines all functional mixins.
"""

from typing import Optional
from .base import OntologyBase
from .component_ops import ComponentMixin
from .attribute_ops import AttributeMixin
from .mapping_ops import MappingMixin


class OntologyFunctions(OntologyBase, ComponentMixin, AttributeMixin, MappingMixin):
    """
    Complete ontology management functions combining all mixins

    Provides functionality for:
    - Core file operations (base)
    - Component CRUD and hierarchy (component_ops)
    - Attribute CRUD, linking, categories (attribute_ops)
    - Mapping operations and GraphDB uploads (mapping_ops)
    """

    def __init__(self,
                 storage=None,
                 workspace_id: Optional[str] = None,
                 graphdb_client=None,
                 ontology_dir: Optional[str] = None,
                 nextcloud_client=None,
                 nextcloud_global_client=None):
        """
        Initialize ontology functions.

        Args:
            storage: WorkspaceStorage for the active workspace (handles local,
                NextCloud and any fsspec backend). Preferred over ontology_dir.
            workspace_id: Workspace ID (used for reporting / local fallback).
            graphdb_client: UnifiedGraphDBClient for GraphDB operations.
            ontology_dir: Local ``.../ontology`` dir — only used to derive a
                local storage when ``storage`` isn't supplied.
            nextcloud_client / nextcloud_global_client: ignored (back-compat).
        """
        super().__init__(
            storage=storage,
            workspace_id=workspace_id,
            graphdb_client=graphdb_client,
            ontology_dir=ontology_dir,
        )


def create_ontology_functions(storage=None,
                              workspace_id: Optional[str] = None,
                              graphdb_client=None,
                              ontology_dir: Optional[str] = None,
                              nextcloud_client=None,
                              nextcloud_global_client=None) -> OntologyFunctions:
    """Factory function to create an OntologyFunctions instance.

    Pass a WorkspaceStorage (``storage=ctx.storage``) for backend-agnostic I/O;
    ``ontology_dir`` remains as a local-only fallback for non-UI callers.
    """
    return OntologyFunctions(
        storage=storage,
        workspace_id=workspace_id,
        graphdb_client=graphdb_client,
        ontology_dir=ontology_dir,
    )


__all__ = ['OntologyFunctions', 'create_ontology_functions']