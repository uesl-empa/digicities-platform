# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Collections & descriptive statistics over attribute values (backend).

Dataset-level analysis for a workspace replica: materialize a ``dici_onto:Set``
(all values of one attribute type) or a ``dici_onto:GroupedSet`` (one attribute
type partitioned by another — GROUP BY) into the ``<http://collections>`` named
graph, with descriptive statistics computed in Python per datatype family.

Collections are derived, recomputable artefacts — a workspace data reload
clears the collections graph (see backend.workspace.graphdb_provisioning).
"""

from .registry import (
    BOOLEAN, CATEGORICAL, NUMERIC, TEMPORAL,
    CollectionError, MixedFamilyError, compute_stats, sniff_family,
)
from .materializer import (
    COMPUTED_BY, delete_collection, detect_family,
    materialize_grouped_set, materialize_set,
)
from .queries import (
    list_collections, member_count, set_bins, set_statistics,
    workspace_attribute_types, workspace_datasets,
)

__all__ = [
    "NUMERIC", "CATEGORICAL", "TEMPORAL", "BOOLEAN",
    "CollectionError", "MixedFamilyError", "compute_stats", "sniff_family",
    "COMPUTED_BY", "detect_family", "materialize_set",
    "materialize_grouped_set", "delete_collection",
    "list_collections", "member_count", "set_bins", "set_statistics",
    "workspace_attribute_types", "workspace_datasets",
]
