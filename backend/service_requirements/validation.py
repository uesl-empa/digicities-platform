# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Validate configured component attributes against the ontology mappings.

Pure functions over the component model: no session state, no rendering. The
report shape (errors / warnings / successes / summary) is pinned by
``tests/goldens/service_requirements_validation.json``.
"""
from __future__ import annotations

from typing import Any, Container, Dict, List, Mapping, Sequence

from backend.service_requirements.models import ComponentEntry


def validate_component_attributes(
    component_entries: Sequence[ComponentEntry],
    known_components: Container[str],
    attribute_mappings: Mapping[str, List[str]],
) -> Dict[str, Any]:
    """Check every configured component-attribute pair against the ontology.

    ``known_components`` holds the component names the ontology knows (dict or
    set — membership is all that's used); ``attribute_mappings`` maps component
    name -> valid attribute names. ``label`` is always valid. Returns the
    report dict: ``errors`` (unknown component / invalid attribute),
    ``warnings`` (components without mappings), ``successes``, and a
    ``summary`` with counts.
    """
    validation_report: Dict[str, Any] = {
        'errors': [],
        'warnings': [],
        'successes': [],
        'summary': {
            'total_attributes': 0,
            'valid_attributes': 0,
            'invalid_attributes': 0,
            'unmapped_components': 0
        }
    }

    if not component_entries:
        validation_report['warnings'].append("No components configured to validate")
        return validation_report

    for entry in component_entries:
        component_name = entry.component_type
        component_path = entry.path

        # Check if component exists in ontology
        if component_name not in known_components:
            validation_report['errors'].append({
                'type': 'UNKNOWN_COMPONENT',
                'component': component_name,
                'path': component_path,
                'message': f"Component '{component_name}' not found in ontology"
            })
            validation_report['summary']['unmapped_components'] += 1
            continue

        # Check if component has any mapped attributes
        if (component_name not in attribute_mappings or
                not attribute_mappings[component_name]):
            validation_report['warnings'].append({
                'type': 'NO_MAPPINGS',
                'component': component_name,
                'path': component_path,
                'message': f"Component '{component_name}' has no attribute mappings in Triplestore"
            })
            validation_report['summary']['unmapped_components'] += 1

        # Get valid attributes for this component
        valid_attributes = []
        if component_name in attribute_mappings:
            valid_attributes = attribute_mappings[component_name]

        # Check each configured attribute
        for attr_name, attr_types in entry.configured_attributes.items():
            validation_report['summary']['total_attributes'] += 1

            # Special case: 'label' is always valid
            if attr_name == 'label':
                validation_report['successes'].append({
                    'component': component_name,
                    'path': component_path,
                    'attribute': attr_name,
                    'types': attr_types,
                    'message': f"✓ Standard attribute 'label' is valid"
                })
                validation_report['summary']['valid_attributes'] += 1
                continue

            # Check if attribute is in the valid list for this component
            if attr_name in valid_attributes:
                validation_report['successes'].append({
                    'component': component_name,
                    'path': component_path,
                    'attribute': attr_name,
                    'types': attr_types,
                    'message': f"✓ Attribute '{attr_name}' is valid for '{component_name}'"
                })
                validation_report['summary']['valid_attributes'] += 1
            else:
                validation_report['errors'].append({
                    'type': 'INVALID_ATTRIBUTE',
                    'component': component_name,
                    'path': component_path,
                    'attribute': attr_name,
                    'types': attr_types,
                    'message': f"Attribute '{attr_name}' is not valid for component '{component_name}'",
                    'suggestion': f"Valid attributes for '{component_name}': {', '.join(valid_attributes) if valid_attributes else 'None'}"
                })
                validation_report['summary']['invalid_attributes'] += 1

    return validation_report


def get_validation_suggestions(
    report: Dict[str, Any], mappings_loaded: bool = True,
) -> List[str]:
    """Actionable next steps derived from a validation report.

    ``mappings_loaded`` says whether any component-attribute mappings are
    available at all (the Streamlit shim reads that from session state).
    """
    suggestions = []

    if report['summary']['unmapped_components'] > 0:
        suggestions.append("🔄 **Reload component-attribute mappings** from Triplestore in the Data Source tab")

    if report['summary']['invalid_attributes'] > 0:
        suggestions.append("🗑️ **Remove invalid attributes** from the Attributes tab")
        suggestions.append("🔍 **Check ontology** to verify which attributes are valid for each component")

    if report['summary']['total_attributes'] == 0:
        suggestions.append("🎯 **Configure attributes** for your components in the Attributes tab")

    if not mappings_loaded:
        suggestions.append("📊 **Load Triplestore mappings** to enable validation")

    return suggestions
