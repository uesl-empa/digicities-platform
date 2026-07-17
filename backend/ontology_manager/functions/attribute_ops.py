# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Attribute Operations
File: components/ontology_manager/functions/attributes.py

Mixin for attribute CRUD operations, linking, categories, and named individuals.
"""

import rdflib
from rdflib import Namespace, RDF, RDFS, Literal, URIRef, OWL, BNode
from typing import List, Dict, Tuple

dici_onto = Namespace("https://digicities.info/ontology#")


class AttributeMixin:
    """Mixin for attribute operations"""

    # =================== Query Operations ===================

    def explore_attributes(self, extension_filename: str) -> List[Dict[str, str]]:
        """Get all attributes (subclasses of Attribute)"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?attribute ?label WHERE {
              ?attribute rdfs:subClassOf* dici_onto:Attribute .
              OPTIONAL { ?attribute rdfs:label ?label. }
            }
            """
            results = g.query(query)
            attribute_data = []
            for row in results:
                attribute_data.append({
                    "class": str(row.attribute),
                    "label": str(row.label) if row.label else ""
                })
            return attribute_data
        except Exception as e:
            print(f"Error exploring attributes: {e}")
            return []

    def explore_attributes_by_type(self, extension_filename: str,
                                   attribute_type: str) -> List[Dict[str, str]]:
        """Get attributes by specific type"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            type_map = {
                "SimpleCost": "SimpleCostAttribute",
                "UnitBasedCost": "UnitBasedCostAttribute",
                "Categorical": "CategoricalAttribute",
                "CustomPhysicalRatio": "CustomPhysicalRatioAttribute",
                "Event": "EventAttribute",
                "SimpleValue": "SimpleValueAttribute"
            }

            ontology_class = type_map.get(attribute_type, "Attribute")

            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?attribute ?label WHERE {{
              ?attribute rdfs:subClassOf* dici_onto:{ontology_class} .
              OPTIONAL {{ ?attribute rdfs:label ?label. }}
            }}
            """
            results = g.query(query)

            attribute_data = []
            for row in results:
                attribute_data.append({
                    "class": str(row.attribute),
                    "label": str(row.label) if row.label else ""
                })
            return attribute_data
        except Exception as e:
            print(f"Error exploring attributes by type: {e}")
            return []

    def get_component_attributes(self, extension_filename: str,
                                 component_uri: str) -> List[Dict[str, str]]:
        """Get all attributes linked to a specific component"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            component_local = component_uri.split('#')[-1]
            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?attribute ?label WHERE {{
              dici_onto:has{component_local}Attribute rdfs:range ?attribute .
              OPTIONAL {{ ?attribute rdfs:label ?label. }}
            }}
            """

            results = g.query(query)
            attributes = []
            for row in results:
                attributes.append({
                    "class": str(row.attribute),
                    "label": str(row.label) if row.label else ""
                })
            return attributes
        except Exception as e:
            print(f"Error getting component attributes: {e}")
            return []

    # =================== Attribute CRUD Operations ===================

    def add_attribute(self, extension_filename: str, attribute_type: str,
                      attribute_label: str, qudt_unit: str = "",
                      y_qudt_unit: str = "", x_unit: str = "",
                      temporal_precision: str = "", parent_property: str = "") -> Tuple[bool, str]:
        """Add a new attribute to the ontology"""
        try:
            # Validate type-specific requirements
            if attribute_type in ["Physical", "Geospatial", "Unit-Based Cost"] and not qudt_unit:
                return False, f"QUDT unit is required for {attribute_type} attributes"

            if attribute_type == "Curve" and (not qudt_unit or not y_qudt_unit):
                return False, "Both X and Y axis units are required for Curve attributes"

            if attribute_type == "CustomPhysicalRatio" and (not x_unit or not y_qudt_unit):
                return False, "Both X and Y units are required for CustomPhysicalRatio"

            if attribute_type == "Event" and not temporal_precision:
                return False, "Temporal precision is required for Event attributes"

            new_attribute = "".join(attribute_label.split())

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            new_attribute_uri = dici_onto[new_attribute]

            # Add basic class definition
            ext_graph.add((new_attribute_uri, RDF.type, OWL.Class))
            ext_graph.add((new_attribute_uri, RDFS.label, Literal(attribute_label)))

            # Handle parent relationship
            if parent_property:
                parent_local = parent_property.split('#')[-1]
                parent_property_uri = dici_onto[parent_local]
                ext_graph.add((new_attribute_uri, RDFS.subClassOf, parent_property_uri))
            else:
                # Make it a direct subclass of the appropriate attribute type class
                type_class_map = {
                    "Physical": dici_onto.PhysicalAttribute,
                    "Simple Cost": dici_onto.SimpleCostAttribute,
                    "Unit-Based Cost": dici_onto.UnitBasedCostAttribute,
                    "Curve": dici_onto.CurveAttribute,
                    "Categorical": dici_onto.CategoricalAttribute,
                    "Geospatial": dici_onto.GeospatialAttribute,
                    "CustomPhysicalRatio": dici_onto.CustomPhysicalRatioAttribute,
                    "Event": dici_onto.EventAttribute,
                    "SimpleValue": dici_onto.SimpleValueAttribute
                }
                ext_graph.add((new_attribute_uri, RDFS.subClassOf, type_class_map[attribute_type]))

            # Handle different attribute types with their specific properties
            if attribute_type in ["Physical", "Geospatial"]:
                default_unit = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultUnit, default_unit))

            elif attribute_type == "Unit-Based Cost":
                selected_unit_uri = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultUnit, selected_unit_uri))
                restriction_bnode = BNode()
                ext_graph.add((restriction_bnode, RDF.type, OWL.Restriction))
                ext_graph.add((restriction_bnode, OWL.onProperty, URIRef("http://qudt.org/schema/qudt/unit")))
                ext_graph.add((restriction_bnode, OWL.hasValue, selected_unit_uri))
                ext_graph.add((new_attribute_uri, RDFS.subClassOf, restriction_bnode))

            elif attribute_type == "Curve":
                default_units_bnode = BNode()
                x_unit_uri = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
                y_unit_uri = URIRef("http://qudt.org/vocab/unit/" + y_qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultUnit, default_units_bnode))
                ext_graph.add((default_units_bnode, dici_onto.xUnit, x_unit_uri))
                ext_graph.add((default_units_bnode, dici_onto.yUnit, y_unit_uri))

            elif attribute_type == "CustomPhysicalRatio":
                ratio_units_bnode = BNode()
                x_unit_uri = URIRef("http://qudt.org/vocab/unit/" + x_unit)
                y_unit_uri = URIRef("http://qudt.org/vocab/unit/" + y_qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasRatioUnits, ratio_units_bnode))
                ext_graph.add((ratio_units_bnode, dici_onto.numeratorUnit, x_unit_uri))
                ext_graph.add((ratio_units_bnode, dici_onto.denominatorUnit, y_unit_uri))

            elif attribute_type == "Event":
                precision_uri = dici_onto[temporal_precision]
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultTemporalPrecision, precision_uri))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Attribute added successfully"
        except Exception as e:
            return False, f"Error adding attribute: {str(e)}"

    def set_default_unit(self, extension_filename: str, attribute: str,
                         qudt_unit: str) -> Tuple[bool, str]:
        """Set (or replace) ``dici_onto:hasDefaultUnit`` on an existing attribute class.

        The repeatable, backend-driven way to give an attribute class its unit
        (rather than hand-editing TTL). Mirrors :meth:`add_attribute`'s load/save
        flow so the temp graph and per-workspace export stay in sync.

        Args:
            extension_filename: the extension to edit, or ``CORE_ONTOLOGY_MODIFICATION``.
            attribute: the attribute class — full IRI or local name (e.g.
                ``LumpedHeatCapacity`` or ``https://digicities.info/ontology#LumpedHeatCapacity``).
            qudt_unit: a QUDT unit *local code* (e.g. ``KiloW``, ``M2``, ``KiloW-HR-PER-K``).

        Returns:
            ``(ok, message)``.
        """
        try:
            if not qudt_unit or not qudt_unit.strip():
                return False, "A QUDT unit code is required"
            qudt_unit = qudt_unit.strip()

            # Validate against the vendored QUDT vocabulary (same source the
            # Ontology Manager unit dropdown uses) — never write an arbitrary
            # string. If the list can't be loaded, fall through rather than
            # hard-fail on an infrastructure issue.
            valid_units = self.get_qudt_units()
            if valid_units and qudt_unit not in valid_units:
                return False, (f"'{qudt_unit}' is not a recognised QUDT unit code "
                               f"(not present in the vendored qudt_units.txt)")

            local = attribute.split('#')[-1].split('/')[-1]
            attr_uri = dici_onto[local]

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            if (attr_uri, RDF.type, OWL.Class) not in ext_graph:
                return False, f"Attribute class '{local}' not found in {extension_filename}"

            # Replace any existing default unit (idempotent / re-runnable).
            for existing in list(ext_graph.objects(attr_uri, dici_onto.hasDefaultUnit)):
                ext_graph.remove((attr_uri, dici_onto.hasDefaultUnit, existing))
            unit_uri = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
            ext_graph.add((attr_uri, dici_onto.hasDefaultUnit, unit_uri))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, f"Default unit for '{local}' set to unit:{qudt_unit}"
        except Exception as e:
            return False, f"Error setting default unit: {str(e)}"

    def remove_attribute(self, extension_filename: str, attribute_uri: str) -> Tuple[bool, str]:
        """Remove an attribute and all its associated triples"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            attribute_ref = URIRef(attribute_uri)

            # Remove all triples where this attribute is the subject
            triples_to_remove = list(ext_graph.triples((attribute_ref, None, None)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            # Remove all triples where this attribute is the object
            triples_to_remove = list(ext_graph.triples((None, None, attribute_ref)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            # Remove specific properties that reference this attribute
            attribute_local = attribute_uri.split('#')[-1]
            all_triples = list(ext_graph.triples((None, None, None)))
            for subject, predicate, obj in all_triples:
                if attribute_local in str(predicate):
                    ext_graph.remove((subject, predicate, obj))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Attribute removed successfully"
        except Exception as e:
            return False, f"Error removing attribute: {str(e)}"

    def link_attribute(self, extension_filename: str, component: str,
                       attribute_property: str) -> Tuple[bool, str]:
        """Link an attribute to a component"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            component_local = component.split('#')[1]
            property_name = attribute_property.split('#')[1]
            general_property = dici_onto["has" + component_local + "Attribute"]
            attribute_property_uri = URIRef(attribute_property)

            # Ensure the complete component attribute hierarchy exists
            self.create_component_attribute_hierarchy_safe(ext_graph, component_local, URIRef(component))

            # Make the attribute a subclass of the component's attribute category
            component_attribute_class = dici_onto[component_local + "Attribute"]
            ext_graph.add((attribute_property_uri, RDFS.subClassOf, component_attribute_class))

            # Check if this specific range already exists
            existing_specific_range = False
            for triple in ext_graph.triples((general_property, RDFS.range, attribute_property_uri)):
                existing_specific_range = True
                break

            # Add the range relationship
            if not existing_specific_range:
                ext_graph.add((general_property, RDFS.range, attribute_property_uri))

            # Create the specific property for this attribute
            specific_property = dici_onto["has" + component_local + property_name]

            # Check if the specific property already exists
            specific_exists = False
            for triple in ext_graph.triples((specific_property, RDF.type, OWL.ObjectProperty)):
                specific_exists = True
                break

            if not specific_exists:
                ext_graph.add((specific_property, RDF.type, OWL.ObjectProperty))
                ext_graph.add((specific_property, RDFS.subPropertyOf, general_property))
                ext_graph.add((specific_property, RDFS.range, attribute_property_uri))
                ext_graph.add((specific_property, RDFS.domain, URIRef(component)))

            # Ensure the general property has the correct domain
            has_domain = False
            for triple in ext_graph.triples((general_property, RDFS.domain, URIRef(component))):
                has_domain = True
                break

            if not has_domain:
                ext_graph.add((general_property, RDFS.domain, URIRef(component)))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Attribute linked to component successfully"
        except Exception as e:
            return False, f"Error linking attribute: {str(e)}"

    def remove_attribute_link(self, extension_filename: str, component_uri: str,
                              attribute_uri: str) -> Tuple[bool, str]:
        """Remove the link between a component and an attribute"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            component_local = component_uri.split('#')[-1]
            attribute_local = attribute_uri.split('#')[-1]
            attribute_ref = URIRef(attribute_uri)

            # Remove general property range
            general_property = dici_onto["has" + component_local + "Attribute"]
            ext_graph.remove((general_property, RDFS.range, attribute_ref))

            # Remove specific property and all its triples
            specific_property = dici_onto["has" + component_local + attribute_local]
            triples_to_remove = list(ext_graph.triples((specific_property, None, None)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Attribute link removed successfully"
        except Exception as e:
            return False, f"Error removing attribute link: {str(e)}"

    def create_component_attribute_hierarchy_safe(self, graph: rdflib.Graph,
                                                  component_local: str,
                                                  component_uri: URIRef):
        """Create the complete attribute hierarchy without interfering with existing properties"""
        parent_component_uri = None
        for triple in graph.triples((component_uri, RDFS.subClassOf, None)):
            if str(triple[2]).startswith(str(dici_onto)):
                parent_component_uri = triple[2]
                break

        if parent_component_uri:
            component_chain = self.get_component_hierarchy_chain(graph, parent_component_uri)
            component_chain.append(component_local)

            previous_attribute_class = dici_onto["ComponentAttribute"]

            for comp_local in component_chain:
                current_attribute_class = dici_onto[comp_local + "Attribute"]

                attribute_exists = False
                for triple in graph.triples((current_attribute_class, RDF.type, OWL.Class)):
                    attribute_exists = True
                    break

                if not attribute_exists:
                    graph.add((current_attribute_class, RDF.type, OWL.Class))
                    graph.add((current_attribute_class, RDFS.subClassOf, previous_attribute_class))
                    graph.add((current_attribute_class, RDFS.label, Literal(comp_local + " Attribute")))

                previous_attribute_class = current_attribute_class

            component_property = dici_onto["has" + component_local + "Attribute"]

            property_exists = False
            for triple in graph.triples((component_property, RDF.type, OWL.ObjectProperty)):
                property_exists = True
                break

            if not property_exists:
                parent_local = str(parent_component_uri).split('#')[-1]
                parent_property = dici_onto["has" + parent_local + "Attribute"]

                graph.add((component_property, RDF.type, OWL.ObjectProperty))
                graph.add((component_property, RDFS.subPropertyOf, parent_property))
                graph.add((component_property, RDFS.domain, component_uri))

    # =================== Category Management ===================

    def get_attribute_categories(self, extension_filename: str) -> List[Dict[str, str]]:
        """Get all attribute categories (classes ending with 'Attribute')"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?category ?label WHERE {
              ?category rdfs:subClassOf* dici_onto:Attribute .
              ?category rdfs:label ?label .
              FILTER(CONTAINS(STR(?category), "Attribute"))
            }
            """

            results = g.query(query)
            categories = []
            for row in results:
                categories.append({
                    "class": str(row.category),
                    "label": str(row.label) if row.label else ""
                })
            return categories
        except Exception as e:
            print(f"Error getting attribute categories: {e}")
            return []

    def get_attribute_categories_for_attribute(self, extension_filename: str,
                                               attribute_uri: str) -> List[Dict[str, str]]:
        """Get all categories that an attribute belongs to"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?category ?label WHERE {{
              <{attribute_uri}> rdfs:subClassOf ?category .
              ?category rdfs:subClassOf* dici_onto:Attribute .
              FILTER(CONTAINS(STR(?category), "Attribute"))
              OPTIONAL {{ ?category rdfs:label ?label. }}
            }}
            """

            results = g.query(query)
            categories = []
            for row in results:
                categories.append({
                    "class": str(row.category),
                    "label": str(row.label) if row.label else ""
                })
            return categories
        except Exception as e:
            print(f"Error getting categories for attribute: {e}")
            return []

    def add_attribute_to_category(self, extension_filename: str, attribute_uri: str,
                                  category_uri: str) -> Tuple[bool, str]:
        """Add an attribute to a category by making it a subclass"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            attribute_ref = URIRef(attribute_uri)
            category_ref = URIRef(category_uri)

            ext_graph.add((attribute_ref, RDFS.subClassOf, category_ref))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Attribute added to category successfully"
        except Exception as e:
            return False, f"Error adding attribute to category: {str(e)}"

    def remove_attribute_from_category(self, extension_filename: str,
                                       attribute_uri: str, category_uri: str) -> Tuple[bool, str]:
        """Remove an attribute from a category by removing the subclass relationship"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            attribute_ref = URIRef(attribute_uri)
            category_ref = URIRef(category_uri)

            ext_graph.remove((attribute_ref, RDFS.subClassOf, category_ref))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Attribute removed from category successfully"
        except Exception as e:
            return False, f"Error removing attribute from category: {str(e)}"

    # =================== Named Individuals Management ===================

    def get_categorical_attributes(self, extension_filename: str) -> List[Dict[str, str]]:
        """Get all categorical attributes"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?attribute ?label WHERE {
              ?attribute rdfs:subClassOf+ dici_onto:CategoricalAttribute .
              ?attribute rdfs:label ?label .
              FILTER(?attribute != dici_onto:CategoricalAttribute)
            }
            """

            results = g.query(query)
            attributes = []
            for row in results:
                attributes.append({
                    "class": str(row.attribute),
                    "label": str(row.label) if row.label else ""
                })
            return attributes
        except Exception as e:
            print(f"Error getting categorical attributes: {e}")
            return []

    def get_named_individuals(self, extension_filename: str,
                              attribute_uri: str) -> List[Dict[str, str]]:
        """Get named individuals for a categorical attribute"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT DISTINCT ?individual ?label WHERE {{
              ?individual rdf:type owl:NamedIndividual .
              ?individual rdf:type <{attribute_uri}> .
              OPTIONAL {{ ?individual rdfs:label ?label. }}
            }}
            """

            results = g.query(query)
            individuals = []
            for row in results:
                individuals.append({
                    "uri": str(row.individual),
                    "label": str(row.label) if row.label else str(row.individual).split('#')[-1]
                })
            return individuals
        except Exception as e:
            print(f"Error getting named individuals: {e}")
            return []

    def add_named_individual(self, extension_filename: str, individual_label: str,
                             attribute_uri: str) -> Tuple[bool, str]:
        """Add a named individual to a categorical attribute"""
        try:
            individual_id = "".join(individual_label.split())

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            attribute_ref = URIRef(attribute_uri)
            individual_uri = dici_onto[individual_id]

            ext_graph.add((individual_uri, RDF.type, OWL.NamedIndividual))
            ext_graph.add((individual_uri, RDF.type, attribute_ref))

            if individual_label:
                ext_graph.add((individual_uri, RDFS.label, Literal(individual_label)))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Named individual added successfully"
        except Exception as e:
            return False, f"Error adding named individual: {str(e)}"

    def remove_named_individual(self, extension_filename: str,
                                individual_uri: str) -> Tuple[bool, str]:
        """Remove a named individual"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            individual_ref = URIRef(individual_uri)

            # Remove all triples where this individual is the subject
            triples_to_remove = list(ext_graph.triples((individual_ref, None, None)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            # Remove all triples where this individual is the object
            triples_to_remove = list(ext_graph.triples((None, None, individual_ref)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Named individual removed successfully"
        except Exception as e:
            return False, f"Error removing named individual: {str(e)}"