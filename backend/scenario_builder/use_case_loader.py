# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Headless TTL use-case loader (the Scenario Builder's component extractor).

Moved from ``apps/streamlit/components/scenario_builder/ttl_use_case_loader.py``
(Phase 4a of the backend/UI separation). The class is ~950 lines of pure rdflib
graph parsing; the handful of Streamlit touches it used to make are now seams:

* status/error display   -> ``on_status(level, message)`` callback, no-op by
  default. Levels are ``"warning"``, ``"error"`` and ``"info"`` (the Streamlit
  shim maps them to ``st.warning`` / ``st.error`` / ``st.write``).
* ``st.session_state['current_workspace']``   -> ``workspace_id`` argument
  (the shim resolves it from session state before constructing).
* ``st.session_state['enabled_ttl_data_products']``  -> explicit
  ``enabled_data_products`` argument on :meth:`get_components_by_type` /
  :meth:`get_all_component_types`, falling back to the
  :meth:`_enabled_data_products` hook (returns ``[]`` here; the shim overrides
  it to read session state).
* ``DataProductProcessor`` (Streamlit-heavy, lives under components/)  ->
  injected via the ``data_processor`` argument or the
  :meth:`_create_data_processor` hook (returns ``None`` here; the shim builds
  the real processor). Anything with ``list_private_folders()``,
  ``list_open_folders()`` and ``process_data_product(name, is_private=...)``
  duck-types.

The Streamlit shim at the old path subclasses this and restores the exact old
behavior; headless callers (REST API, scripts, tests) use this class directly.

Behavioral note (load-bearing): unit strings surfaced by the extractors are
QUDT unit *codes* (``KiloW``, ``KiloW-HR``), never display abbreviations
(``kW``) — see ``tests/test_unit_code_roundtrip.py`` and ``backend.units``.
"""
from typing import Callable, Dict, List, Optional

try:
    from rdflib import Graph, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS

    RDFLIB_AVAILABLE = True
except ImportError:
    RDFLIB_AVAILABLE = False

from backend.nextcloud import NextcloudClient


class NextCloudTTLUseCaseLoader:
    """
    Load components from TTL files in NextCloud workspace with updated data product handling
    """

    def __init__(self, workspace_id: str = None, data_processor=None,
                 on_status: Optional[Callable[[str, str], None]] = None):
        """Initialize loader with workspace context.

        Args:
            workspace_id: The workspace to load from. Required for any real
                loading; when falsy the loader degrades to an inert instance
                (and reports it via ``on_status``).
            data_processor: Optional data-product processor (duck-typed). When
                omitted, :meth:`_create_data_processor` decides — ``None``
                headlessly, the Streamlit shim builds the real one.
            on_status: ``(level, message)`` display callback; levels are
                ``"warning"`` / ``"error"`` / ``"info"``. Defaults to a no-op.
        """
        self.workspace_id = workspace_id
        self.on_status = on_status
        self.nextcloud_client = None
        self.data_processor = data_processor  # New data product processor
        self._cached_components = {}
        self._cached_graphs = {}
        self._cached_data_products = {}
        self._component_cache_key = None
        self._initialize_clients()

        # Define namespaces
        self.DICI = Namespace("https://digicities.info/ontology#")
        self.QUDT = Namespace("http://qudt.org/schema/qudt/")
        self.UNIT = Namespace("http://qudt.org/vocab/unit/")
        self.XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
        self.CUR = Namespace("http://qudt.org/vocab/currency/")
        # Legacy alias kept so old workspace TTLs (pre-cur switch) still parse cleanly.
        self.ISO4217 = Namespace("http://example.org/currency/")

        # Define attribute type categories
        self.ATTRIBUTE_TYPES = {
            'PhysicalAttribute': {
                'required_props': ['qudt:value', 'qudt:unit'],
                'optional_props': [],
                'category': 'physical'
            },
            'SimpleCostAttribute': {
                'required_props': ['qudt:value', 'dici_onto:currency'],
                'optional_props': [],
                'category': 'cost'
            },
            'UnitBasedCostAttribute': {
                'required_props': ['qudt:value', 'qudt:unit', 'dici_onto:currency'],
                'optional_props': [],
                'category': 'cost'
            },
            'GeospatialAttribute': {
                'required_props': ['qudt:value', 'qudt:unit'],
                'optional_props': [],
                'category': 'geospatial'
            },
            'DynamicAttribute': {
                'required_props': ['qudt:unit'],
                'optional_props': [
                    'dici_onto:hasLiveTimeSeriesReference',
                    'dici_onto:hasHistoricTimeSeriesReference',
                    'dici_onto:hasFutureTimeSeriesReference',
                    'dici_onto:hasTimeSeriesReference'
                ],
                'category': 'dynamic'
            },
            'CurveAttribute': {
                'required_props': ['dici_onto:hasDataPoints'],
                'optional_props': ['dici_onto:xUnit', 'dici_onto:yUnit'],
                'category': 'curve'
            },
            'CategoricalAttribute': {
                'required_props': [],
                'optional_props': [],
                'category': 'categorical'
            },
            'EventAttribute': {
                'required_props': ['dici_onto:hasTemporalValue'],
                'optional_props': ['dici_onto:hasTemporalPrecision'],
                'category': 'temporal'
            }
        }

    # ------------------------------------------------------------------ seams
    def _notify(self, level: str, message: str) -> None:
        """Report a status/error message. Silent unless ``on_status`` is set."""
        if self.on_status is not None:
            self.on_status(level, message)

    def _create_data_processor(self):
        """Build the data-product processor when none was injected.

        Since the Phase 5 extraction the backend ``DataProductProcessor`` is
        headless (storage-aware, registry-resolved, no session state), so the
        default builds it directly — data products now load in headless
        callers too. The Streamlit shim still overrides this to construct the
        session-aware subclass; explicit ``data_processor`` arguments always
        win over this hook.
        """
        try:
            from backend.data_products import DataProductProcessor

            return DataProductProcessor(workspace_id=self.workspace_id,
                                        on_status=self.on_status)
        except Exception as e:
            self._notify('warning', f"Failed to initialize data processor: {e}")
            return None

    def _enabled_data_products(self) -> List[str]:
        """Default source of enabled data-product ids (``type:name`` strings).

        Headless default: none. The Streamlit shim overrides this to read
        ``st.session_state['enabled_ttl_data_products']``. Explicit
        ``enabled_data_products`` arguments always win over this hook.
        """
        return []

    # ------------------------------------------------------------ initialization
    def _initialize_clients(self):
        """Initialize the data processor (storage-aware) and, when configured, a
        NextCloud client. In local mode the NextCloud client is unavailable —
        that's fine; the DataProductProcessor reads from workspace storage."""
        if not self.workspace_id:
            self._notify('warning', "⚠️ No workspace available for TTL loading")
            self.nextcloud_client = None
            self.data_processor = None
            return

        # NextCloud client is optional — degrade silently when not configured.
        try:
            self.nextcloud_client = NextcloudClient(workspace_id=self.workspace_id)
        except Exception:
            self.nextcloud_client = None

        # Data processor is storage-aware and works in local mode.
        if self.data_processor is None:
            self.data_processor = self._create_data_processor()

    def get_available_private_data_products(self) -> List[Dict]:
        """Get available private data products using the new data processor"""
        if not self.data_processor:
            return []

        cache_key = f"private_data_products_{self.workspace_id}"
        if cache_key in self._cached_data_products:
            return self._cached_data_products[cache_key]

        try:
            # Use the new data processor to list private folders
            private_folders = self.data_processor.list_private_folders()
            data_products = []

            for folder_name in private_folders:
                data_products.append({
                    'name': folder_name,
                    'path': f"{self.workspace_id}/private_data_products/{folder_name}",
                    'type': 'private',
                    'workspace': self.workspace_id,
                    'description': f"Private data product: {folder_name}"
                })

            self._cached_data_products[cache_key] = data_products
            return data_products

        except Exception as e:
            self._notify('warning', f"Error loading private data products: {e}")
            return []

    def get_available_global_data_products(self) -> List[Dict]:
        """Get available global/open data products using the new data processor"""
        if not self.data_processor:
            return []

        cache_key = "global_data_products"
        if cache_key in self._cached_data_products:
            return self._cached_data_products[cache_key]

        try:
            # Use the new data processor to list open folders
            open_folders = self.data_processor.list_open_folders()
            data_products = []

            for folder_name in open_folders:
                data_products.append({
                    'name': folder_name,
                    'path': f"global/open_data_products/{folder_name}",
                    'type': 'global',
                    'workspace': 'global',
                    'description': f"Open data product: {folder_name}"
                })

            self._cached_data_products[cache_key] = data_products
            return data_products

        except Exception as e:
            self._notify('warning', f"Error loading open data products: {e}")
            return []

    def load_data_product_ttl(self, data_product: Dict) -> Optional["Graph"]:
        """Load a specific data product TTL file using the new data processor"""
        if not RDFLIB_AVAILABLE:
            return None

        try:
            # Check cache first
            cache_key = f"dp_graph_{data_product['type']}_{data_product['name']}"
            if cache_key in self._cached_graphs:
                return self._cached_graphs[cache_key]

            # Use the data processor to load the data product
            if not self.data_processor:
                self._notify('warning', f"Data processor not available for {data_product['name']}")
                return None

            # Process the data product to get its TTL content
            processed_product = self.data_processor.process_data_product(
                data_product['name'],
                is_private=(data_product['type'] == 'private')
            )

            if not processed_product or not processed_product.get('ttl_content'):
                self._notify('warning', f"Could not load TTL for {data_product['name']}")
                return None

            ttl_content = processed_product['ttl_content']

            # Create and configure graph
            graph = Graph()

            # Bind namespaces
            graph.bind("dici_onto", self.DICI)
            graph.bind("qudt", self.QUDT)
            graph.bind("unit", self.UNIT)
            graph.bind("rdfs", RDFS)
            graph.bind("xsd", self.XSD)
            graph.bind("cur", self.CUR)
            graph.bind("iso4217", self.ISO4217)  # legacy

            # Parse the TTL content
            graph.parse(data=ttl_content, format="turtle")

            # Cache the graph
            self._cached_graphs[cache_key] = graph

            return graph

        except Exception as load_error:
            self._notify('error', f"Error loading TTL {data_product['name']}: {str(load_error)}")
            return None

    def get_components_by_type(self, component_type: str,
                               enabled_data_products: Optional[List[str]] = None) -> List[Dict]:
        """Get components with proper cache invalidation based on enabled data products"""
        # Create cache key that includes enabled data products
        if enabled_data_products is None:
            enabled_data_products = self._enabled_data_products()
        enabled_products = enabled_data_products
        cache_key = f"{self.workspace_id}:{component_type}:{','.join(sorted(enabled_products))}"

        # Check if cache is still valid
        if cache_key in self._cached_components:
            return self._cached_components[cache_key]

        all_components = []

        # Load from workspace knowledge graph (now via GraphDB export, not NextCloud)
        try:
            graph = self.load_workspace_classes_and_attributes()
            if graph:
                components_by_type = self.extract_components_from_graph(graph, f"workspace_{self.workspace_id}")
                workspace_components = components_by_type.get(component_type, [])
                all_components.extend(workspace_components)
        except Exception:
            # Silently fail - workspace graphs are loaded via GraphDB export mode
            pass

        # Load from enabled data products only
        for data_product_id in enabled_products:
            if ':' in data_product_id:
                dp_type, dp_name = data_product_id.split(':', 1)
                data_product = {
                    'name': dp_name,
                    'type': dp_type,
                    'path': f"{'private_data_products' if dp_type == 'private' else 'open_data_products'}/{dp_name}"
                }

                try:
                    dp_components_by_type = self.get_components_from_data_product(data_product)
                    if dp_components_by_type:
                        dp_components = dp_components_by_type.get(component_type, [])
                        all_components.extend(dp_components)
                except Exception as e:
                    self._notify('info', f"Error loading {dp_name}: {e}")

        # Cache with the new key
        self._cached_components[cache_key] = all_components
        return all_components

    def get_all_component_types(self,
                                enabled_data_products: Optional[List[str]] = None) -> List[str]:
        """Get all available component types with proper cache handling"""
        all_types = set()

        # Get types from workspace knowledge graph (now via GraphDB export, not NextCloud)
        try:
            graph = self.load_workspace_classes_and_attributes()
            if graph:
                components_by_type = self.extract_components_from_graph(graph, f"workspace_{self.workspace_id}")
                all_types.update(components_by_type.keys())
        except Exception:
            # Silently fail - workspace graphs are loaded via GraphDB export mode
            pass

        # Get types from enabled data products
        if enabled_data_products is None:
            enabled_data_products = self._enabled_data_products()

        for data_product_id in enabled_data_products:
            if ':' in data_product_id:
                dp_type, dp_name = data_product_id.split(':', 1)
                data_product = {
                    'name': dp_name,
                    'type': dp_type,
                    'path': f"{'private_data_products' if dp_type == 'private' else 'open_data_products'}/{dp_name}"
                }

                try:
                    dp_components_by_type = self.get_components_from_data_product(data_product)
                    if dp_components_by_type:
                        all_types.update(dp_components_by_type.keys())
                except Exception as e:
                    self._notify('info', f"Error getting types from {dp_name}: {e}")

        return sorted(list(all_types))

    def get_components_from_data_product(self, data_product: Dict) -> Dict[str, List[Dict]]:
        """Extract components from a data product TTL file"""
        graph = self.load_data_product_ttl(data_product)
        if not graph:
            return {}

        components_by_type = self.extract_components_from_graph(
            graph,
            f"data_product_{data_product['type']}_{data_product['name']}"
        )

        # Add data product metadata to components
        for comp_type, components in components_by_type.items():
            for component in components:
                component['source'] = 'data_product'
                component['data_product_name'] = data_product['name']
                component['data_product_type'] = data_product['type']
                component['workspace_id'] = self.workspace_id if data_product['type'] == 'private' else 'global'

        return components_by_type

    def clear_cache(self):
        """Clear all caches completely.

        The Streamlit shim extends this to also drop its session-state caches.
        """
        self._cached_components.clear()
        self._cached_graphs.clear()
        self._cached_data_products.clear()

    def load_workspace_classes_and_attributes(self) -> Optional["Graph"]:
        """
        Load the main classes_and_attributes.ttl file from workspace.

        NOTE: This method is deprecated and returns None.
        Workspace knowledge graphs are now loaded via GraphDB export mode instead.
        This method is kept for backward compatibility but no longer attempts NextCloud loading.
        """
        # DISABLED: NextCloud workspace loading is no longer needed
        # Components are now loaded from GraphDB export mode (see scenario_builder_components.py)
        return None

    def load_ttl_from_nextcloud(self, file_path: str) -> Optional["Graph"]:
        """
        Load TTL file from NextCloud into RDFLib graph.

        NOTE: This method is kept for backward compatibility with data products,
        but no longer outputs error messages for missing workspace files since
        workspace knowledge graphs are now loaded via GraphDB export mode.
        """
        if not RDFLIB_AVAILABLE or not self.nextcloud_client:
            return None

        try:
            cache_key = f"{self.workspace_id}:{file_path}"
            if cache_key in self._cached_graphs:
                return self._cached_graphs[cache_key]

            ttl_content = self.nextcloud_client.download_text_file(file_path)

            if not ttl_content:
                return None

            graph = Graph()

            graph.bind("dici_onto", self.DICI)
            graph.bind("qudt", self.QUDT)
            graph.bind("unit", self.UNIT)
            graph.bind("rdfs", RDFS)
            graph.bind("xsd", self.XSD)
            graph.bind("cur", self.CUR)
            graph.bind("iso4217", self.ISO4217)  # legacy

            graph.parse(data=ttl_content, format="turtle")

            self._cached_graphs[cache_key] = graph
            return graph

        except Exception:
            # Silently fail - workspace graphs are now loaded via GraphDB export
            return None

    def extract_components_from_graph(self, graph: "Graph", source_file: str) -> Dict[str, List[Dict]]:
        """Extract components from RDFLib graph with enhanced attribute type handling"""
        components_by_type = {}

        for subject, predicate, obj in graph.triples((None, RDF.type, None)):
            if str(obj).startswith(str(self.DICI)):
                component_type = str(obj).replace(str(self.DICI), "")
                component_uri = str(subject)

                if not self._is_attribute_instance(component_type):
                    component_data = self._extract_component_data(graph, subject, component_type)

                    if component_data:
                        if component_type not in components_by_type:
                            components_by_type[component_type] = []

                        component_data.setdefault('source', 'ttl_use_case')
                        component_data.setdefault('source_file', source_file)
                        component_data.setdefault('workspace_id', self.workspace_id)

                        components_by_type[component_type].append(component_data)

        return components_by_type

    def _is_attribute_instance(self, type_name: str) -> bool:
        """Check if a type represents an attribute instance rather than a component"""
        attribute_indicators = [
            'Attribute', 'Cost', 'Power', 'Curve', 'Production', 'Height',
            'Diameter', 'Elevation', 'Latitude', 'Longitude', 'Roughness',
            'Irradiance', 'Efficiency', 'CAPEX', 'OPEX', 'TimeSeries'
        ]
        return any(indicator in type_name for indicator in attribute_indicators)

    def _extract_component_data(self, graph: "Graph", component_uri: "URIRef", component_type: str) -> Optional[Dict]:
        """Extract complete component data from graph with enhanced attribute handling"""
        try:
            component = {
                'uri': str(component_uri),
                'label': self._get_label(graph, component_uri),
                'type': component_type,
                'attributes': {},
                'relationships': [],
                'nested_properties': {}
            }

            component['attributes']['URI'] = {
                'value': str(component_uri),
                'unit': 'uri',
                'attribute_type': 'system',
                'category': 'system'
            }

            component['attributes']['label'] = {
                'value': component['label'],
                'unit': 'text',
                'attribute_type': 'system',
                'category': 'system'
            }

            for predicate, attr_uri in graph.predicate_objects(component_uri):
                predicate_str = str(predicate)

                if 'hasAttribute' in predicate_str or (predicate_str.startswith(str(self.DICI)) and 'Attribute' in predicate_str):
                    attr_name = self._extract_attribute_name_from_predicate(predicate_str)
                    if attr_name:
                        attr_data = self._extract_enhanced_attribute_details(graph, attr_uri, attr_name)
                        if attr_data:
                            component['attributes'][attr_name] = attr_data

                            nested_props = self._extract_nested_properties(graph, attr_uri, attr_name)
                            if nested_props:
                                component['nested_properties'][attr_name] = nested_props

            component_uri_str = str(component_uri)

            for attr_subject in graph.subjects():
                attr_subject_str = str(attr_subject)

                if (attr_subject_str.startswith(component_uri_str + '/') and
                        attr_subject_str.count('/') == component_uri_str.count('/') + 1):

                    attr_name = attr_subject_str.split('/')[-1]

                    attr_types = [str(t).replace(str(self.DICI), "") for _, _, t in graph.triples((attr_subject, RDF.type, None)) if str(t).startswith(str(self.DICI))]

                    if self._is_new_categorical_attribute(attr_types):
                        attr_data = self._extract_new_categorical_attribute_data(graph, attr_subject, attr_name, attr_types)
                        if attr_data:
                            component['attributes'][attr_name] = attr_data
                    else:
                        for attr_type_obj in graph.objects(attr_subject, RDF.type):
                            attr_type_str = str(attr_type_obj)
                            if (attr_type_str.startswith(str(self.DICI)) and
                                    any(attr_type in attr_type_str for attr_type in self.ATTRIBUTE_TYPES.keys())):

                                attr_data = self._extract_enhanced_attribute_details(graph, attr_subject, attr_name)
                                if attr_data:
                                    component['attributes'][attr_name] = attr_data

                                    nested_props = self._extract_nested_properties(graph, attr_subject, attr_name)
                                    if nested_props:
                                        component['nested_properties'][attr_name] = nested_props
                                break

            return component

        except Exception as e:
            self._notify('warning', f"Error extracting component data for {component_uri}: {str(e)}")
            return None

    def _get_label(self, graph: "Graph", uri: "URIRef") -> str:
        """Get rdfs:label for a URI"""
        for label in graph.objects(uri, RDFS.label):
            return str(label)
        return str(uri).split('/')[-1]

    def _extract_attribute_name_from_predicate(self, predicate_str: str) -> Optional[str]:
        """Extract attribute name from predicate URI with enhanced pattern matching"""
        if str(self.DICI) in predicate_str:
            local_part = predicate_str.replace(str(self.DICI), "")

            if local_part.startswith('has') and local_part.endswith('Attribute'):
                attr_part = local_part[3:-9]

                component_types = [
                    'WindTurbine', 'GlobalWindAtlasSite', 'Region', 'EnergyCarrier',
                    'PV', 'SolarPanel', 'Battery', 'Grid', 'Load', 'Generator', 'Building'
                ]
                for comp_type in component_types:
                    if attr_part.startswith(comp_type):
                        attr_part = attr_part[len(comp_type):]
                        break

                return attr_part if attr_part else None

            elif local_part == 'hasAttribute':
                return 'hasAttribute'

        return None

    def _is_new_categorical_attribute(self, attr_types: List[str]) -> bool:
        """Check if this follows the new categorical attribute structure"""
        if 'CategoricalAttribute' not in attr_types:
            return False
        if len(attr_types) < 3:
            return False
        non_categorical_types = [t for t in attr_types if t != 'CategoricalAttribute']
        return len(non_categorical_types) >= 2

    def _extract_new_categorical_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_name: str, attr_types: List[str]) -> Optional[Dict]:
        """Extract data for new categorical attribute structure - FIXED VERSION"""
        try:
            uri_fragment = str(attr_uri).split('/')[-1]
            non_categorical_types = [t for t in attr_types if t != 'CategoricalAttribute']

            if len(non_categorical_types) < 1:
                return None

            attribute_type = None
            categorical_value = None

            if uri_fragment in non_categorical_types:
                attribute_type = uri_fragment
                for type_name in non_categorical_types:
                    if type_name != uri_fragment:
                        categorical_value = type_name
                        break
            else:
                for type_name in non_categorical_types:
                    if any(pattern in type_name for pattern in ['Type', 'Supply', 'Category', 'Class', 'Mode', 'Status']):
                        attribute_type = type_name
                        break

                for type_name in non_categorical_types:
                    if type_name != attribute_type:
                        categorical_value = type_name
                        break

            if len(non_categorical_types) == 1 and not categorical_value:
                categorical_value = non_categorical_types[0]
                attribute_type = uri_fragment

            attr_data = {
                'uri': str(attr_uri),
                'value': categorical_value if categorical_value else "Unknown",
                'category_value': categorical_value if categorical_value else "Unknown",
                'unit': 'category',
                'attribute_type': 'CategoricalAttribute',
                'category': 'categorical',
                'data_type': 'categorical',
                'specific_attribute_type': attribute_type if attribute_type else uri_fragment
            }

            return attr_data

        except Exception as e:
            self._notify('warning', f"Error extracting categorical attribute data for {attr_uri}: {str(e)}")
            return None

    def _extract_enhanced_attribute_details(self, graph: "Graph", attr_uri: "URIRef", attr_name: str) -> Optional[Dict]:
        """Extract attribute value, unit, type, and other details from graph"""
        try:
            attr_data = {
                'uri': str(attr_uri),
                'attribute_type': 'unknown',
                'category': 'unknown'
            }

            attribute_types = []
            for attr_type in graph.objects(attr_uri, RDF.type):
                if str(attr_type).startswith(str(self.DICI)):
                    type_name = str(attr_type).replace(str(self.DICI), "")
                    attribute_types.append(type_name)

            if 'CategoricalAttribute' in attribute_types:
                uri_fragment = str(attr_uri).split('/')[-1]
                category_value = None
                for type_name in attribute_types:
                    if type_name != 'CategoricalAttribute' and type_name != uri_fragment:
                        category_value = type_name
                        break

                if category_value:
                    attr_data['attribute_type'] = 'CategoricalAttribute'
                    attr_data['category'] = 'categorical'
                    attr_data['value'] = category_value
                    attr_data['category_value'] = category_value
                    attr_data['unit'] = 'category'
                    attr_data['data_type'] = 'categorical'
                    attr_data['specific_attribute_type'] = uri_fragment
                    return attr_data
                else:
                    return self._extract_new_categorical_attribute_data(graph, attr_uri, attr_name, attribute_types)

            primary_type = self._determine_primary_attribute_type(attribute_types)
            if primary_type:
                attr_data['attribute_type'] = primary_type
                attr_data['category'] = self.ATTRIBUTE_TYPES[primary_type]['category']

            if primary_type == 'PhysicalAttribute' or primary_type == 'GeospatialAttribute':
                self._extract_physical_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'SimpleCostAttribute':
                self._extract_simple_cost_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'UnitBasedCostAttribute':
                self._extract_unit_based_cost_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'DynamicAttribute':
                self._extract_dynamic_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'CurveAttribute':
                self._extract_curve_attribute_data(graph, attr_uri, attr_data)
            elif primary_type == 'EventAttribute':
                self._extract_event_attribute_data(graph, attr_uri, attr_data)
            else:
                self._extract_generic_attribute_data(graph, attr_uri, attr_data)

            if ('value' in attr_data or 'time_series_reference' in attr_data or
                    'data_points' in attr_data or 'category_value' in attr_data or
                    'temporal_value' in attr_data):
                if 'unit' not in attr_data:
                    attr_data['unit'] = 'dimensionless'
                return attr_data

            return None

        except Exception as e:
            self._notify('warning', f"Error extracting attribute details for {attr_uri}: {str(e)}")
            return None

    def _determine_primary_attribute_type(self, attribute_types: List[str]) -> Optional[str]:
        """Determine the primary attribute type from a list of types"""
        priority_order = [
            'EventAttribute',
            'CategoricalAttribute',
            'DynamicAttribute',
            'CurveAttribute',
            'UnitBasedCostAttribute',
            'SimpleCostAttribute',
            'GeospatialAttribute',
            'PhysicalAttribute'
        ]

        for priority_type in priority_order:
            if priority_type in attribute_types:
                return priority_type

        return None

    def _extract_physical_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Extract data for PhysicalAttribute and GeospatialAttribute"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

    def _extract_simple_cost_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Extract data for SimpleCostAttribute"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for currency in graph.objects(attr_uri, self.DICI.currency):
            attr_data['currency'] = self._map_currency_uri_to_string(str(currency))

        if 'currency' in attr_data:
            attr_data['unit'] = attr_data['currency']

    def _extract_unit_based_cost_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Extract data for UnitBasedCostAttribute"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

        for currency in graph.objects(attr_uri, self.DICI.currency):
            attr_data['currency'] = self._map_currency_uri_to_string(str(currency))

    def _extract_dynamic_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Extract data for DynamicAttribute"""
        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

        time_series_props = [
            ('hasLiveTimeSeriesReference', 'live'),
            ('hasHistoricTimeSeriesReference', 'historic'),
            ('hasFutureTimeSeriesReference', 'future'),
            ('hasTimeSeriesReference', 'generic')
        ]

        for prop_name, series_type in time_series_props:
            prop_uri = getattr(self.DICI, prop_name)
            for ref_value in graph.objects(attr_uri, prop_uri):
                attr_data['time_series_reference'] = str(ref_value)
                attr_data['time_series_type'] = series_type
                attr_data['value'] = f"Time series: {str(ref_value)}"
                break

        for ts_uri in graph.objects(attr_uri, self.DICI.hasLiveTimeSeries):
            attr_data['time_series_uri'] = str(ts_uri)
        for ts_uri in graph.objects(attr_uri, self.DICI.hasHistoricTimeSeries):
            attr_data['time_series_uri'] = str(ts_uri)
        for ts_uri in graph.objects(attr_uri, self.DICI.hasFutureTimeSeries):
            attr_data['time_series_uri'] = str(ts_uri)

    def _extract_curve_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Extract data for CurveAttribute"""
        for data_points in graph.objects(attr_uri, self.DICI.hasDataPoints):
            attr_data['data_points'] = str(data_points)
            attr_data['value'] = str(data_points)
            attr_data['unit'] = 'data_points'
            attr_data['data_type'] = 'curve'

        for x_unit in graph.objects(attr_uri, self.DICI.xUnit):
            attr_data['x_unit'] = self._map_unit_uri_to_string(str(x_unit))

        for y_unit in graph.objects(attr_uri, self.DICI.yUnit):
            attr_data['y_unit'] = self._map_unit_uri_to_string(str(y_unit))

    def _extract_categorical_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict, attribute_types: List[str]):
        """Extract data for CategoricalAttribute"""
        uri_fragment = str(attr_uri).split('/')[-1]
        category_value = None

        for attr_type in attribute_types:
            if attr_type != 'CategoricalAttribute' and attr_type != uri_fragment:
                category_value = attr_type
                break

        if not category_value:
            for attr_type in attribute_types:
                if (attr_type != 'CategoricalAttribute' and
                        attr_type != uri_fragment and
                        not any(pattern in attr_type for pattern in ['Type', 'Supply', 'Category', 'Class'])):
                    category_value = attr_type
                    break

        if category_value:
            attr_data['value'] = category_value
            attr_data['category_value'] = category_value
            attr_data['unit'] = 'category'
            attr_data['data_type'] = 'categorical'
            attr_data['specific_attribute_type'] = uri_fragment
        else:
            self._notify('warning', f"Could not determine categorical value for {attr_uri}")
            attr_data['value'] = "Unknown"
            attr_data['category_value'] = "Unknown"
            attr_data['unit'] = 'category'
            attr_data['data_type'] = 'categorical'
            attr_data['specific_attribute_type'] = uri_fragment

    def _extract_event_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Extract data for EventAttribute (temporal data)"""
        for temporal_value in graph.objects(attr_uri, self.DICI.hasTemporalValue):
            temporal_str = str(temporal_value)
            attr_data['temporal_value'] = temporal_str
            attr_data['value'] = temporal_str
            attr_data['unit'] = 'temporal'
            attr_data['data_type'] = 'temporal'

        for precision in graph.objects(attr_uri, self.DICI.hasTemporalPrecision):
            precision_str = str(precision).replace(str(self.DICI), "")
            attr_data['temporal_precision'] = precision_str

        if 'temporal_value' not in attr_data:
            for value in graph.objects(attr_uri, self.QUDT.value):
                fallback_value = str(value)
                attr_data['temporal_value'] = fallback_value
                attr_data['value'] = fallback_value
                attr_data['unit'] = 'temporal'
                attr_data['data_type'] = 'temporal'
                break

    def _extract_generic_attribute_data(self, graph: "Graph", attr_uri: "URIRef", attr_data: Dict):
        """Fallback generic attribute extraction"""
        for value in graph.objects(attr_uri, self.QUDT.value):
            attr_data['value'] = self._convert_literal_value(value)

        for unit in graph.objects(attr_uri, self.QUDT.unit):
            attr_data['unit'] = self._map_unit_uri_to_string(str(unit))

    def _extract_nested_properties(self, graph: "Graph", attr_uri: "URIRef", attr_name: str) -> Dict:
        """Extract nested properties for complex attributes"""
        nested_props = {}

        time_series_props = [
            'hasLiveTimeSeries',
            'hasHistoricTimeSeries',
            'hasFutureTimeSeries',
            'hasTimeSeries'
        ]

        for prop_name in time_series_props:
            prop_uri = getattr(self.DICI, prop_name)
            for ts_uri in graph.objects(attr_uri, prop_uri):
                nested_props[prop_name] = str(ts_uri)

                ts_unit = None
                for unit_obj in graph.objects(ts_uri, self.QUDT.unit):
                    ts_unit = self._map_unit_uri_to_string(str(unit_obj))
                    break

                if ts_unit:
                    nested_props[f"{prop_name}_unit"] = ts_unit

        reference_props = [
            'hasLiveTimeSeriesReference',
            'hasHistoricTimeSeriesReference',
            'hasFutureTimeSeriesReference',
            'hasTimeSeriesReference'
        ]

        for prop_name in reference_props:
            prop_uri = getattr(self.DICI, prop_name)
            for ref_value in graph.objects(attr_uri, prop_uri):
                nested_props[prop_name] = str(ref_value)

        return nested_props

    def _convert_literal_value(self, literal_value):
        """Convert RDF literal to appropriate Python type"""
        if hasattr(literal_value, 'datatype'):
            datatype = str(literal_value.datatype) if literal_value.datatype else None

            if datatype:
                if 'decimal' in datatype or 'float' in datatype or 'double' in datatype:
                    try:
                        return float(str(literal_value))
                    except:
                        return str(literal_value)
                elif 'int' in datatype:
                    try:
                        return int(str(literal_value))
                    except:
                        return str(literal_value)

        return str(literal_value)

    def _map_unit_uri_to_string(self, unit_uri: str) -> str:
        """Return the QUDT unit *code* (local name) from a unit URI or CURIE.

        e.g. ``http://qudt.org/vocab/unit/KiloW`` -> ``KiloW``,
             ``unit:KiloW-HR``                     -> ``KiloW-HR``.

        Previously this down-mapped to lossy display abbreviations
        (``KiloW`` -> ``kW``, ``KiloW-HR`` -> ``kW-HR``), which downstream TTL
        emitters could not turn back into a valid ``qudt:unit <.../KiloW>`` IRI —
        yielding ``<.../kW-HR>`` or ``UNITLESS``. Keeping the QUDT code
        round-trips cleanly; the replica also carries ``dici_onto:hasUnitLabel``
        for friendly UI display.

        An absent unit returns '' rather than a made-up code: the local-name split
        used to turn the bare namespace into the word ``unit``, and ``unit:None``
        into ``None``. See backend.units.
        """
        from backend.units import unit_local_name
        return unit_local_name(unit_uri)

    def _map_currency_uri_to_string(self, currency_uri: str) -> str:
        """Map currency URIs to readable strings"""
        currency_mapping = {
            # Current — QUDT currency vocabulary
            'http://qudt.org/vocab/currency/CHF': 'CHF',
            'http://qudt.org/vocab/currency/EUR': 'EUR',
            'http://qudt.org/vocab/currency/USD': 'USD',
            'cur:CHF': 'CHF',
            'cur:EUR': 'EUR',
            'cur:USD': 'USD',
            # Legacy — pre-cur switch
            'http://example.org/currency/CHF': 'CHF',
            'http://example.org/currency/EUR': 'EUR',
            'http://example.org/currency/USD': 'USD',
            'iso4217:CHF': 'CHF',
            'iso4217:EUR': 'EUR',
            'iso4217:USD': 'USD',
        }

        return currency_mapping.get(currency_uri, currency_uri.split('/')[-1])

    def get_nested_property_value(self, component: Dict, property_path: str) -> Optional[str]:
        """Get value for nested property paths"""
        if '.' not in property_path:
            return None

        parts = property_path.split('.')
        if len(parts) < 2:
            return None

        base_attribute = parts[0]
        nested_property = parts[1]

        if base_attribute in component.get('attributes', {}):
            nested_props = component.get('nested_properties', {}).get(base_attribute, {})
            if nested_property in nested_props:
                return nested_props[nested_property]

            attr_data = component['attributes'][base_attribute]
            if nested_property in attr_data:
                return attr_data[nested_property]

        return None


__all__ = ["NextCloudTTLUseCaseLoader", "RDFLIB_AVAILABLE"]
