# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Pure TTL -> service-payload converter (no Streamlit).

Extracted from the API submission Convert tab so the same conversion can run
outside the UI: in notebooks, tests, and from the command line. The Streamlit
tab (components/api_submission_module/ttl_convert.py) imports from here, so this
module is the single source of truth for the conversion logic.

It walks a scenario's ComponentLink graph and applies a service template's
attribute -> ontology-term mapping, producing the JSON/YAML payload a service
receives.

CLI:
    python -m backend.api_submission.ttl_converter <template.yaml> <scenario.ttl>
"""
import json
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import yaml

try:
    import rdflib
    from rdflib import Graph, URIRef, Literal, Namespace
    from rdflib.graph import ReadOnlyGraphAggregate
    from rdflib.namespace import RDF, RDFS, XSD
    RDFLIB_AVAILABLE = True

    from backend.ontology_kinds import (
        AttributeKind, core_graph, in_dici_namespace, is_attribute_class,
        is_attribute_node, is_attribute_predicate, is_component_link_class,
        is_scenario_class, is_subproperty_of, is_time_series_reference_predicate,
        kind_of_node, superclasses,
    )
except ImportError:
    RDFLIB_AVAILABLE = False

yaml.add_representer(
    OrderedDict,
    lambda dumper, data: dumper.represent_mapping("tag:yaml.org,2002:map", data.items()),
)


def preprocess_ttl_content(ttl_content: str) -> str:
    """Preprocess TTL content to fix common syntax issues."""
    lines = ttl_content.split('\n')
    processed_lines = []
    in_multiline_string = False
    current_string_lines = []
    string_delimiter = None

    i = 0
    while i < len(lines):
        line = lines[i]

        if not in_multiline_string:
            if 'qudt:value' in line and ('"[' in line or "\"[" in line):
                quote_count = line.count('"')
                if quote_count % 2 == 1:
                    in_multiline_string = True
                    current_string_lines = [line]
                    string_delimiter = '"'
                else:
                    processed_lines.append(line)
            else:
                processed_lines.append(line)
        else:
            current_string_lines.append(line)
            if string_delimiter in line:
                quote_count = line.count(string_delimiter)
                if quote_count % 2 == 1:
                    fixed_string_line = fix_multiline_string_value(current_string_lines)
                    processed_lines.append(fixed_string_line)
                    in_multiline_string = False
                    current_string_lines = []
                    string_delimiter = None
        i += 1

    if in_multiline_string and current_string_lines:
        fixed_string_line = fix_multiline_string_value(current_string_lines)
        processed_lines.append(fixed_string_line)

    return '\n'.join(processed_lines)


def fix_multiline_string_value(lines: List[str]) -> str:
    """Fix multiline string values."""
    if not lines:
        return ""

    first_line = lines[0]
    if 'qudt:value' not in first_line:
        return first_line

    parts = first_line.split('qudt:value', 1)
    prefix = parts[0] + 'qudt:value'

    string_content = ""
    if len(parts) > 1:
        value_part = parts[1].strip()
        if value_part.startswith('"'):
            string_content = value_part[1:]

        for line in lines[1:]:
            string_content += '\n' + line

        if '"' in string_content:
            quote_pos = string_content.rfind('"')
            trailing_part = string_content[quote_pos + 1:]
            string_content = string_content[:quote_pos]
        else:
            trailing_part = " ;"

    string_content = string_content.replace('\r\n', '\n').replace('\r', '\n')

    if '[' in string_content and ']' in string_content:
        cleaned = re.sub(r'\s+', ' ', string_content.strip())
        cleaned = cleaned.replace('[ ', '[').replace(' ]', ']')
        cleaned = cleaned.replace('"', '\\"')
        return f'{prefix} "{cleaned}"{trailing_part}'
    else:
        escaped = string_content.replace('\n', '\\n').replace('"', '\\"')
        return f'{prefix} "{escaped}"{trailing_part}'


class RobustTTL2YAMLProcessor:
    """
    Fixed processor that handles unlimited levels of CL links while preserving
    all existing functionality for implicit component references and TTL processing.
    Now properly handles nested link specifications within link templates.
    Modified to always return arrays for all link results.
    """

    def __init__(self, ontology_graph: Optional["Graph"] = None):
        if not RDFLIB_AVAILABLE:
            raise ImportError("rdflib is required for TTL processing")

        self.g = Graph()
        # What a node or class IS is read from the ontology hierarchy: the
        # scenario data, the workspace schema when the caller has it, and the
        # vendored core (always). Built once the TTL is parsed.
        self.ontology_graph = ontology_graph
        self.view = None
        self.DICI = Namespace("https://digicities.info/ontology#")
        self.QUDT = Namespace("http://qudt.org/schema/qudt/")
        self.current_scenario = None
        self.debug = False

        # Indexes and caches
        self.typed_nodes = []       # every typed node except scenarios and links
        self.component_links = []
        self._classes_cache = {}    # node -> every class it is an instance of
        self._instances_cache = {}  # template class name -> its instances

    def process(self, template_content: Dict, ttl_source: str, is_ttl_file: bool = True, debug: bool = False) -> OrderedDict:
        """Main processing method."""
        self.debug = debug

        # Parse TTL
        try:
            if is_ttl_file:
                with open(ttl_source, 'r', encoding='utf-8') as f:
                    ttl_content = f.read()
                fixed_content = preprocess_ttl_content(ttl_content)
                self.g.parse(data=fixed_content, format="turtle")
            else:
                fixed_content = preprocess_ttl_content(ttl_source)
                self.g.parse(data=fixed_content, format="turtle")
        except Exception as e:
            if self.debug:
                print(f"Error parsing TTL: {e}")
            raise e

        self.view = ReadOnlyGraphAggregate(
            [g for g in (self.g, self.ontology_graph) if g is not None] + [core_graph()])

        # Find scenario
        scenarios = list(self.g.subjects(RDF.type, self.DICI.Scenario))
        if not scenarios:
            raise ValueError("No scenario found in TTL")
        self.current_scenario = scenarios[0]

        if self.debug:
            print(f"Found scenario: {self.current_scenario}")

        # Build indexes
        self._build_indexes()

        # 'connection' is registration metadata (where the service listens), not
        # part of the payload the service receives - drop it before processing.
        if isinstance(template_content, dict) and 'connection' in template_content:
            template_content = {k: v for k, v in template_content.items() if k != 'connection'}

        # Process template
        return self._process_value(template_content, context_component=None)

    def _build_indexes(self):
        """Build indexes of components and links for efficient lookup."""
        # Every typed node except the scenario and its ComponentLinks (by the
        # hierarchy), ordered by IRI: graph order depends on how the scenario
        # was materialized, and the payload must not change from run to run.
        # Which template class a node answers to is asked per class
        # (``_is_a``), never read off a name.
        self.typed_nodes = []
        self._classes_cache = {}
        self._instances_cache = {}
        for s in sorted(set(self.g.subjects(RDF.type, None)), key=str):
            if any(is_scenario_class(self.view, t) or is_component_link_class(self.view, t)
                   for t in self.g.objects(s, RDF.type)):
                continue
            self.typed_nodes.append(s)

        # Index component links, ordered by their ends for the same reason.
        self.component_links = []
        for link in self.g.subjects(RDF.type, self.DICI.ComponentLink):
            sources = sorted(self.g.objects(link, self.DICI.hasInputEntity), key=str)
            targets = sorted(self.g.objects(link, self.DICI.linksInputyEntityTo), key=str)
            if sources and targets:
                self.component_links.append({
                    'source': sources[0],
                    'target': targets[0]
                })
        self.component_links.sort(key=lambda link: (str(link['source']), str(link['target'])))

        if self.debug:
            print(f"Indexed {len(self.typed_nodes)} typed nodes")
            print(f"Indexed {len(self.component_links)} links")

    # A template names classes and properties by their dici_onto: local name
    # (``WindTurbine.HubHeight``). The token becomes that IRI; a token that
    # cannot be a local name names nothing.
    _LOCAL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")

    def _term(self, name: str) -> Optional[URIRef]:
        """The dici_onto: IRI a template token names, or None."""
        if not isinstance(name, str) or not self._LOCAL_NAME.fullmatch(name):
            return None
        return self.DICI[name]

    def _classes_of(self, node) -> set:
        """Every class ``node`` is an instance of: its rdf:types and their
        superclasses in the data, the workspace schema and the core."""
        cached = self._classes_cache.get(node)
        if cached is None:
            cached = set()
            for t in self.g.objects(node, RDF.type):
                cached |= superclasses(self.view, t)
            self._classes_cache[node] = cached
        return cached

    def _is_a(self, node, type_name: str) -> bool:
        """``node`` is an instance of the class the template names."""
        cls = self._term(type_name)
        return cls is not None and cls in self._classes_of(node)

    def _instances_of(self, type_name: str) -> List[URIRef]:
        """Every indexed node that is an instance of the named class."""
        if type_name not in self._instances_cache:
            self._instances_cache[type_name] = [
                n for n in self.typed_nodes if self._is_a(n, type_name)]
        return self._instances_cache[type_name]

    def _type_label(self, node) -> str:
        """The node's asserted classes, for debug output only."""
        return ", ".join(sorted(self._extract_name(str(t)) for t in self.g.objects(node, RDF.type)))

    def _process_value(self, value: Any, context_component: Optional[URIRef]) -> Any:
        """Process any value based on its type and context."""

        if self.debug:
            print(f"\n_process_value called with context: {self._extract_name(str(context_component)) if context_component else 'None'}")
            print(f"Value type: {type(value)}")
            if isinstance(value, dict):
                print(f"Dict keys: {list(value.keys())}")

        if isinstance(value, dict):
            # FIRST: Check for link specifications - this is a complete link structure
            if 'link' in value and 'template' in value:
                if self.debug:
                    print(f">>> FOUND LINK SPEC: {value.get('link')}")

                # Extract any additional fields that aren't 'link' or 'template'
                additional_fields = {}
                for k, v in value.items():
                    if k not in ['link', 'template']:
                        additional_fields[k] = v

                if self.debug and additional_fields:
                    print(f">>> LINK HAS ADDITIONAL FIELDS: {list(additional_fields.keys())}")

                return self._process_link(
                    value['link'],
                    value['template'],
                    context_component,
                    additional_fields if additional_fields else None
                )

            # SECOND: Check if this dict contains implicit component references
            component_type = self._detect_implicit_component_type(value)
            if component_type:
                if self.debug:
                    print(f">>> FOUND IMPLICIT COMPONENT: {component_type}")

                # If we already have a context of this type, use it
                if context_component and self._is_a(context_component, component_type):
                    if self.debug:
                        print(f"Using existing context for {component_type}")
                    result = OrderedDict()
                    for k, v in value.items():
                        processed = self._process_value(v, context_component)
                        if processed is not None:
                            result[k] = processed
                    return result

                # Otherwise find components of this type
                components = self._find_components_for_context(component_type, None)

                if components:
                    # MODIFIED: Always return as array for implicit components too
                    results = []
                    for comp in components:
                        result = self._process_value(value, comp)
                        if result:
                            results.append(result)
                    return results if results else []

            # THIRD: Regular dict - process each key-value pair
            if self.debug:
                print(f">>> PROCESSING REGULAR DICT with {len(value)} keys")
            result = OrderedDict()
            for k, v in value.items():
                if self.debug:
                    print(f"Processing dict key: {k}")
                    if isinstance(v, dict) and 'link' in v:
                        print(f"  >>> KEY {k} CONTAINS NESTED LINK: {v.get('link')}")
                processed = self._process_value(v, context_component)
                if processed is not None:
                    result[k] = processed
                elif self.debug:
                    print(f"  Key {k} returned None")
            return result

        elif isinstance(value, str):
            return self._resolve_string_value(value, context_component)
        else:
            return value

    def _detect_implicit_component_type(self, template_dict: Dict) -> Optional[str]:
        """Detect if a dict contains implicit references to a component type."""
        # Skip detection if this is a link specification
        if 'link' in template_dict and 'template' in template_dict:
            return None

        for key, value in template_dict.items():
            if isinstance(value, str) and '.' in value:
                parts = value.split('.')
                if len(parts) >= 2 and self._instances_of(parts[0]):
                    return parts[0]
        return None

    def _find_components_for_context(self, component_type: str, context: Optional[URIRef]) -> List[URIRef]:
        """Find components of given type, considering context."""
        if context:
            # Find components linked to context
            return self._find_linked_components(context, component_type)
        else:
            # Find components linked to scenario
            return self._find_linked_components(self.current_scenario, component_type)

    def _find_linked_components(self, source: URIRef, target_type: str) -> List[URIRef]:
        """Find all components of target_type linked to source."""
        results = []

        for link in self.component_links:
            # Check forward links (source -> target)
            if link['source'] == source:
                target = link['target']
                if self._is_a(target, target_type):
                    results.append(target)

            # Check reverse links (target -> source)
            if link['target'] == source:
                target = link['source']
                if self._is_a(target, target_type):
                    results.append(target)

        return results

    def _process_link(self, link_spec: str, template: Any, context: Optional[URIRef], additional_fields: Optional[Dict] = None) -> Any:
        """
        Process CL.X.Y link specifications with support for unlimited hierarchical levels.
        Now also processes additional fields that may contain nested links.
        Modified to always return arrays.
        """
        if self.debug:
            context_info = f"context: {self._extract_name(str(context))} ({self._type_label(context)})" if context else "no context"
            print(f"\n*** PROCESSING LINK: {link_spec} with {context_info} ***")

        if not link_spec.startswith('CL.'):
            return None

        parts = link_spec.split('.')
        if len(parts) != 3:
            return None

        source_type = parts[1]
        target_type = parts[2]

        # Determine sources based on link specification and context
        sources = []

        # The template names classes; the ontology says which one is a Scenario.
        source_cls = self._term(source_type)
        if source_cls is not None and is_scenario_class(self.view, source_cls):
            sources = [self.current_scenario]
        elif context and self._is_a(context, source_type):
            # Use the current context as source
            sources = [context]
            if self.debug:
                print(f"Using context as source: {self._extract_name(str(context))}")
        else:
            # Look up components of source_type
            sources = self._instances_of(source_type)

        if self.debug:
            print(f"Sources ({source_type}): {len(sources)}")

        # Find all targets linked from sources
        all_targets = []
        for source in sources:
            targets = self._find_linked_components(source, target_type)
            if self.debug and targets:
                print(f"Found {len(targets)} {target_type}(s) from {self._extract_name(str(source))}")
            all_targets.extend(targets)

        # Remove duplicates while preserving order
        unique_targets = []
        seen = set()
        for target in all_targets:
            if target not in seen:
                unique_targets.append(target)
                seen.add(target)

        if self.debug:
            print(f"Total unique {target_type}(s): {len(unique_targets)}")

        if not unique_targets:
            return []

        # Process template for each target with the target as new context
        results = []
        for target in unique_targets:
            if self.debug:
                print(f"\n*** PROCESSING TEMPLATE FOR {self._extract_name(str(target))} ***")
                print(f"Template structure: {template}")

            # Process the template with this target as the new context
            result = self._process_value(template, target)

            if self.debug:
                print(f"Template result for {self._extract_name(str(target))}: {result}")

            # Now process any additional fields (like nested EnergyCarrier links)
            if additional_fields:
                if self.debug:
                    print(f"Processing additional fields: {list(additional_fields.keys())}")

                for field_name, field_value in additional_fields.items():
                    if isinstance(field_value, dict) and 'link' in field_value and 'template' in field_value:
                        if self.debug:
                            print(f"Found nested link in field '{field_name}': {field_value['link']}")

                        # Extract nested additional fields if any
                        nested_additional = {}
                        for k, v in field_value.items():
                            if k not in ['link', 'template']:
                                nested_additional[k] = v

                        # Process this nested link with the current target as context
                        nested_result = self._process_link(
                            field_value['link'],
                            field_value['template'],
                            target,
                            nested_additional if nested_additional else None
                        )

                        if nested_result is not None:
                            if result is None:
                                result = OrderedDict()
                            elif not isinstance(result, OrderedDict):
                                result = OrderedDict(result) if isinstance(result, dict) else OrderedDict()
                            result[field_name] = nested_result

            if result is not None:
                results.append(result)

        if self.debug:
            print(f"*** LINK {link_spec} COMPLETE: {len(results)} results ***")

        # MODIFIED: Always return as array
        return results if results else []

    def _resolve_string_value(self, value: str, context: Optional[URIRef]) -> Any:
        """Resolve string values that may contain references."""

        # Handle Scenario references
        if value == 'Scenario.URI':
            return str(self.current_scenario)
        elif value == 'Scenario.label':
            labels = list(self.g.objects(self.current_scenario, RDFS.label))
            return str(labels[0]) if labels else self._extract_name(str(self.current_scenario))

        # Parse component.attribute references
        if '.' in value:
            parts = value.split('.')
            if len(parts) >= 2:
                comp_type = parts[0]

                # Check if we have context of the right type
                if context and self._is_a(context, comp_type):
                    if parts[1].lower() == 'uri':
                        return str(context)
                    elif parts[1].lower() == 'label':
                        labels = list(self.g.objects(context, RDFS.label))
                        return str(labels[0]) if labels else self._extract_name(str(context))
                    else:
                        # Get attribute value
                        if len(parts) == 2:
                            return self._get_attribute_value(context, comp_type, parts[1])
                        else:
                            # Nested attribute
                            return self._get_nested_attribute(context, comp_type, parts[1:])

        return value

    def _find_attribute(self, component: URIRef, comp_type: str, attr_name: str) -> Optional[URIRef]:
        """The component's attribute node for ``attr_name``, or None.

        ``attr_name`` names an attribute class. The node is the one the
        component links through an attribute edge (a predicate under
        ``dici_onto:hasAttribute``, or any edge to an attribute node) that IS an
        instance of that class. Only that node may be used: taking the first
        attribute linked handed a missing attribute some other attribute's
        value. An untyped node is no attribute of any class.
        """
        want = self._term(attr_name)
        if want is None:
            return None
        for pred, node in self.g.predicate_objects(component):
            if not isinstance(node, URIRef) or want not in self._classes_of(node):
                continue
            if is_attribute_predicate(self.view, pred) or is_attribute_node(self.view, node):
                return node
        return None

    def _get_attribute_value(self, component: URIRef, comp_type: str, attr_name: str) -> Any:
        """Get attribute value from component."""
        attr = self._find_attribute(component, comp_type, attr_name)
        if attr is None:
            return None
        return self._extract_attribute_value(attr, attr_name)

    def _get_nested_attribute(self, component: URIRef, comp_type: str, attr_path: List[str]) -> Any:
        """Get nested attribute value."""
        if len(attr_path) < 2:
            return None

        # Find intermediate attribute
        attr_uri = self._find_attribute(component, comp_type, attr_path[0])
        if not attr_uri:
            return None

        # The nested name is a property. A time series reference is read
        # through that property or any of its subproperties, so a request for
        # hasTimeSeriesReference is met by hasLiveTimeSeriesReference.
        prop = self._term(attr_path[1])
        if prop is None or not is_time_series_reference_predicate(self.view, prop):
            return None
        for pred, ref in self.g.predicate_objects(attr_uri):
            if is_subproperty_of(self.view, pred, prop):
                return str(ref)
        return None

    def _category_value(self, attr_uri: URIRef, attr_name: Optional[str]) -> Optional[str]:
        """The category a categorical attribute holds: its
        ``dici_onto:hasCategoricalValue``, else the DigiCities type that is
        neither an attribute class (by the hierarchy) nor the attribute class
        the template asked for (``attr_name``; needed when the caller passed no
        workspace schema, so the extension's attribute classes are unknown)."""
        for value in self.g.objects(attr_uri, self.DICI.hasCategoricalValue):
            return self._extract_name(str(value))
        want = self._term(attr_name) if attr_name else None
        for t in self.g.objects(attr_uri, RDF.type):
            if t == want or not in_dici_namespace(t) or is_attribute_class(self.view, t):
                continue
            return self._extract_name(str(t))
        return None

    def _extract_attribute_value(self, attr_uri: URIRef,
                                 attr_name: Optional[str] = None) -> Any:
        """Extract value from attribute URI. ``attr_name`` is the template's
        name for the attribute."""
        kind = kind_of_node(self.view, attr_uri)

        if kind is AttributeKind.CATEGORICAL:
            category = self._category_value(attr_uri, attr_name)
            if category is not None:
                return category

        # Handle event/temporal
        if kind is AttributeKind.EVENT:
            for val in self.g.objects(attr_uri, self.DICI.hasTemporalValue):
                val_str = str(val)
                year_match = re.search(r'(\d{4})', val_str)
                if year_match:
                    return f"01-01-{year_match.group(1)}"
                return val_str

        # CurveAttribute stores its points in dici_onto:hasDataPoints (a JSON
        # [[x, y], ...] literal) with axis units alongside — return a
        # structured value (previously curves converted to null).
        if kind is AttributeKind.CURVE:
            for val in self.g.objects(attr_uri, self.DICI.hasDataPoints):
                raw = str(val)
                try:
                    points = json.loads(raw)
                except Exception:
                    # Replicas built before the writer emitted JSON hold one
                    # "[x, y]" row per line with no commas between rows. Read
                    # those too; anything else (e.g. a file reference) passes
                    # through as the raw string.
                    points = _legacy_curve_points(raw)
                    if points is None:
                        return raw
                curve: Dict[str, Any] = {'points': points}
                for pred, key in ((self.DICI.xUnitLabel, 'x_unit'),
                                  (self.DICI.yUnitLabel, 'y_unit')):
                    for u in self.g.objects(attr_uri, pred):
                        curve[key] = str(u)
                return curve

        # Handle resource (file/path) references and simple no-unit values.
        # A DataPathAttribute stores its value in dici_onto:hasDataPath (e.g. a
        # weather .epw file reference); SimpleValueAttribute in
        # dici_onto:hasAttributeValue. Neither carries a qudt:value.
        for val in self.g.objects(attr_uri, self.DICI.hasDataPath):
            return self._convert_literal(val)
        for val in self.g.objects(attr_uri, self.DICI.hasAttributeValue):
            return self._convert_literal(val)

        # Handle regular values
        for val in self.g.objects(attr_uri, self.QUDT.value):
            return self._convert_literal(val)

        return None

    def _convert_literal(self, literal) -> Any:
        """Convert RDF literal to Python type."""
        if hasattr(literal, 'datatype'):
            datatype = str(literal.datatype) if literal.datatype else None
            if datatype and any(t in datatype for t in ['decimal', 'float', 'double']):
                try:
                    return float(str(literal))
                except:
                    pass
            elif datatype and 'int' in datatype:
                try:
                    return int(str(literal))
                except:
                    pass
        return str(literal)

    def _extract_name(self, uri: str) -> str:
        """Extract name from URI."""
        return uri.split('/')[-1].split('#')[-1]


def _legacy_curve_points(raw: str) -> Optional[List[List[float]]]:
    """Points from a non-JSON curve literal, or None when it holds none."""
    from backend.replica_builder.utils.ttl_attribute_helpers import parse_curve_points

    points, dropped = parse_curve_points(raw)
    if not points:
        return None
    if dropped:
        print(f"[ttl_converter] curve literal: {dropped} unreadable point(s) "
              f"skipped, {len(points)} kept")
    return points


# Sentinels for the template walk in clean_placeholder_values: the caller gave
# no template at all, vs. a template was given but has nothing at this spot.
_NO_TEMPLATE = object()
_NO_COUNTERPART = object()

# Without a template, only this strict <ClassName>.<AttrName> shape counts as
# an unresolved placeholder.
_STRICT_PLACEHOLDER_RE = re.compile(r'^[A-Z][A-Za-z0-9]*\.[A-Z][A-Za-z0-9_]*$')


def _is_link_spec(t: Any) -> bool:
    return isinstance(t, dict) and 'link' in t and 'template' in t


def _element_template(t: Any) -> Any:
    """The template each element of a converter-expanded list follows: a link
    spec's ``template`` (plus its extra fields), an implicit component block
    itself, the matching item of a literal list."""
    if t is _NO_TEMPLATE or t is _NO_COUNTERPART:
        return t
    if _is_link_spec(t):
        inner = t['template']
        if isinstance(inner, dict):
            merged = dict(inner)
            merged.update({k: v for k, v in t.items() if k not in ('link', 'template')})
            return merged
        return inner
    if isinstance(t, dict):
        return t
    return _NO_COUNTERPART


def _is_unresolved_placeholder(value: str, t: Any) -> bool:
    """True when ``value`` is a template reference the converter handed back
    unresolved. With a template, only a string IDENTICAL to the reference at
    the same position counts (a resolved value never is); without one, only
    the strict ``<ClassName>.<AttrName>`` shape does."""
    if t is _NO_TEMPLATE:
        return bool(_STRICT_PLACEHOLDER_RE.match(value))
    if isinstance(t, str) and value == t:
        from backend.api_submission.validation import _is_reference
        return _is_reference(t)
    return False


def clean_placeholder_values(data: Any, template: Any = _NO_TEMPLATE) -> Any:
    """Remove placeholder values from results.

    Drops unresolved ``.URI`` / ``.label`` / ``_not_found`` markers and any
    template reference that came back unresolved (e.g. ``Building.Height``
    when the component has no such attribute), so a literal reference string
    never reaches a service as if it were data.

    Pass the service ``template`` the payload was converted from: a string is
    then only treated as an unresolved reference when it equals the template's
    reference at that exact position. Without it, only strings of the strict
    ``<ClassName>.<AttrName>`` shape are.
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if template is _NO_TEMPLATE:
                sub = _NO_TEMPLATE
            elif isinstance(template, dict) and not _is_link_spec(template):
                sub = template.get(key, _NO_COUNTERPART)
            else:
                sub = _NO_COUNTERPART
            cleaned_value = clean_placeholder_values(value, sub)
            if cleaned_value is not None:
                cleaned[key] = cleaned_value
        return cleaned if cleaned else None
    elif isinstance(data, list):
        cleaned = []
        for i, item in enumerate(data):
            if isinstance(template, list):
                sub = template[i] if i < len(template) else _NO_COUNTERPART
            else:
                sub = _element_template(template)
            cleaned_item = clean_placeholder_values(item, sub)
            if cleaned_item is not None:
                cleaned.append(cleaned_item)
        return cleaned if cleaned else []
    elif isinstance(data, str):
        # Remove unresolved references
        if any(x in data for x in ['_not_found>', '.URI', '.label'] if '.' in data):
            return None
        if _is_unresolved_placeholder(data, template):
            return None
        return data
    else:
        return data


# --------------------------------------------------------------------------- #
# Convenience API + CLI
# --------------------------------------------------------------------------- #

def convert_scenario(template: Dict, ttl_text: str, *, clean: bool = True,
                     debug: bool = False, ontology_graph=None) -> Dict:
    """Convert a scenario TTL string to a service payload dict.

    ``template`` is the full service template (service_name / description /
    scenario_data), the same dict the Convert tab feeds the processor. Set
    ``clean=False`` to keep unresolved placeholders instead of dropping them.
    ``ontology_graph`` is the workspace schema (core + extension), when the
    caller has it; the vendored core is always used.
    """
    processor = RobustTTL2YAMLProcessor(ontology_graph=ontology_graph)
    payload = processor.process(template, ttl_text, is_ttl_file=False, debug=debug)
    if clean:
        payload = clean_placeholder_values(payload, template) or {}
    return payload


def _main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Convert a Digicities scenario TTL to a service payload "
                    "(JSON/YAML) using a service template - the same conversion "
                    "the API submission Convert tab performs, from the CLI.")
    parser.add_argument("template", help="Service template file (.yaml/.yml/.json)")
    parser.add_argument("scenario", help="Scenario file (.ttl)")
    parser.add_argument("--yaml", action="store_true", help="Emit YAML instead of JSON")
    parser.add_argument("--raw", action="store_true",
                        help="Keep unresolved placeholders (no cleaning)")
    parser.add_argument("--debug", action="store_true", help="Print processing trace")
    parser.add_argument("-o", "--output", help="Write to this file instead of stdout")
    args = parser.parse_args(argv)

    with open(args.template, "r", encoding="utf-8") as f:
        template = yaml.safe_load(f)
    with open(args.scenario, "r", encoding="utf-8") as f:
        ttl_text = f.read()

    payload = convert_scenario(template, ttl_text, clean=not args.raw, debug=args.debug)
    plain = json.loads(json.dumps(payload))  # drop OrderedDict for clean dumping

    if args.yaml:
        out = yaml.safe_dump(plain, sort_keys=False, allow_unicode=True)
    else:
        out = json.dumps(plain, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out + "\n")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
