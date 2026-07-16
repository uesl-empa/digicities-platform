# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# ============================================================================
# components/assumptions/ttl_generator.py
"""
TTL generator for modified scenarios
Leverages existing scenario builder TTL generation infrastructure
"""


def generate_scenario_ttl(scenario_data):
    """
    Generate TTL for a modified scenario
    Uses existing infrastructure from scenario_builder
    """
    scenario_name = scenario_data['scenario_name']
    scenario_uri = f"{scenario_data['namespace']}/{scenario_name.replace(' ', '_')}"
    components = scenario_data['components']

    ttl_lines = [
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "@prefix unit: <http://qudt.org/vocab/unit/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix cur: <http://qudt.org/vocab/currency/> .",
        "",
        "# Scenario declaration",
        f'<{scenario_uri}> a dici_onto:Scenario ;',
        f'    rdfs:label "{scenario_name}" ;',
        f'    dici_onto:generatedBy "AssumptionsModule" ;'
    ]

    # Add assumption metadata
    assumption = scenario_data.get('assumption', {})
    if assumption:
        ttl_lines.append(f'    dici_onto:assumptionApplied "{assumption.get("name", "Unknown")}" ;')
        ttl_lines.append(f'    dici_onto:assumptionId "{scenario_data.get("assumption_id", "")}" ;')

    ttl_lines.extend([
        f'    dici_onto:modifiedComponents "{scenario_data.get("modified_count", 0)}"^^xsd:integer .',
        ""
    ])

    # Add component declarations
    if components:
        ttl_lines.extend([
            "# Component declarations",
            ""
        ])

        for component in components:
            component_uri = component['uri']
            component_type = component['type']
            component_label = component['label']

            ttl_lines.append(f"<{component_uri}> a dici_onto:{component_type} ;")
            ttl_lines.append(f'    rdfs:label "{component_label}" ;')

            # Add source tracking
            if component.get('source') == 'modified':
                ttl_lines.append(f'    dici_onto:sourceType "modified" ;')
                ttl_lines.append(f'    dici_onto:derivedFrom <{component.get("derived_from", "")}> ;')
            else:
                ttl_lines.append(f'    dici_onto:sourceType "unmodified" ;')

            # Add attribute references
            for attr_name, attr_data in component.get('attributes', {}).items():
                if attr_name not in ['URI', 'label']:
                    attr_uri = attr_data.get('uri', f"{component_uri}/{attr_name}")
                    ttl_lines.append(f"    dici_onto:has{attr_name}Attribute <{attr_uri}> ;")

            ttl_lines.append(f'    dici_onto:usedInScenario <{scenario_uri}> .')
            ttl_lines.append("")

            # Add attribute definitions
            for attr_name, attr_data in component.get('attributes', {}).items():
                if attr_name not in ['URI', 'label']:
                    generate_attribute_ttl(ttl_lines, attr_data, scenario_uri)

    return "\n".join(ttl_lines)


def generate_attribute_ttl(ttl_lines, attr_data, scenario_uri):
    """Generate TTL for an attribute"""
    attr_uri = attr_data.get('uri', '')
    attr_type = attr_data.get('attribute_type', 'PhysicalAttribute')

    ttl_lines.append(f"<{attr_uri}> a dici_onto:{attr_type} ;")

    # Add value
    value = attr_data.get('value')
    if value is not None:
        try:
            float_value = float(value)
            ttl_lines.append(f'    qudt:value "{float_value}"^^xsd:decimal ;')
        except (ValueError, TypeError):
            ttl_lines.append(f'    qudt:value "{value}"^^xsd:string ;')

    # Add unit
    unit = attr_data.get('unit', '')
    if unit and unit not in ['', 'dimensionless']:
        ttl_lines.append(f'    qudt:unit unit:{unit} ;')

    # Add currency for cost attributes
    if attr_data.get('category') == 'cost':
        currency = attr_data.get('currency', 'CHF')
        ttl_lines.append(f'    dici_onto:currency cur:{currency} ;')

    ttl_lines.append(f'    dici_onto:usedInScenario <{scenario_uri}> .')
    ttl_lines.append("")