# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Pure-Python ontology manager backend (integrated mode only)."""

from backend.ontology_manager.functions import (
    OntologyFunctions,
    create_ontology_functions,
)
from backend.ontology_manager.instructions import apply_extension_instructions

__all__ = ["OntologyFunctions", "create_ontology_functions",
           "apply_extension_instructions"]
