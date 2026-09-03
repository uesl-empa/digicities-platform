# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Service requirements: the logic half of the Service Requirements Builder.

A service template is a YAML document that declares which component types,
attributes and parent/child links a model needs from a scenario
(``service_name`` + ``connection`` + nested ``scenario_data`` with
``CL.<Parent>.<Child>`` links and ``<Type>.<attr>`` references). This package
owns everything about those templates that is not rendering:

* :mod:`.models` — the component/attribute dataclasses shared by every layer
* :mod:`.ontology` — discovering component and attribute classes (uploaded
  ontology file or triplestore, via ``backend.graphdb.queries``)
* :mod:`.template` — generating a template from configured components, and
  parsing an existing template back into the component model
* :mod:`.validation` — checking configured attributes against the ontology
  mappings
* :mod:`.requirements` — the requirements TTL
  (ComponentAttributeRequirement / ComponentComponentRequirement)

Consumers: the Streamlit shell
(``apps/streamlit/components/service_requirements_builder.py``, a shim that
keeps session state and rendering) and the REST API (``apps/api/service.py``).

Known consumer-side duplicate: the onboarding agent generates the same kind of
template on its own in
``digicities-onboarding-agent/onboarding_agent/core/service_template.py``.
As of this phase the platform generator here is authoritative; unifying the
onboarder onto this package is a follow-up, not done yet. Divergences to
reconcile then: the onboarder wraps root components as children of Scenario
(``CL.Scenario.<Root>``), pluralizes child keys (``heatPumps``), and uses
``name:`` instead of ``label:`` in the ``scenario_data`` header.
"""

from backend.service_requirements.models import (
    AttributeClass,
    ComponentClass,
    ComponentEntry,
)
from backend.service_requirements.ontology import (
    RDFLIB_AVAILABLE,
    extract_local_name,
    load_attribute_mappings,
    load_attribute_mappings_by_convention,
    load_components_and_attributes,
    parse_ontology_content,
)
from backend.service_requirements.template import (
    TS_REFERENCE,
    attribute_field,
    build_service_template,
    camel_case,
    entries_from_path_tree,
    entries_from_type_tree,
    extract_attributes_from_dict,
    list_template_fields,
    parse_service_template,
    parse_yaml_to_components,
    pascal_case,
)
from backend.service_requirements.validation import (
    get_validation_suggestions,
    validate_component_attributes,
)
from backend.service_requirements.requirements import (
    requirements_ttl,
    service_file_id,
)

__all__ = [
    "AttributeClass",
    "ComponentClass",
    "ComponentEntry",
    "RDFLIB_AVAILABLE",
    "extract_local_name",
    "load_attribute_mappings",
    "load_attribute_mappings_by_convention",
    "load_components_and_attributes",
    "parse_ontology_content",
    "TS_REFERENCE",
    "attribute_field",
    "build_service_template",
    "camel_case",
    "entries_from_path_tree",
    "entries_from_type_tree",
    "extract_attributes_from_dict",
    "list_template_fields",
    "parse_service_template",
    "parse_yaml_to_components",
    "pascal_case",
    "get_validation_suggestions",
    "validate_component_attributes",
    "requirements_ttl",
    "service_file_id",
]
