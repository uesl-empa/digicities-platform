# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Component Operations
File: components/ontology_manager/functions/components.py

Mixin for component CRUD operations and hierarchy management.
"""

import rdflib
from rdflib import Namespace, RDF, RDFS, Literal, URIRef, OWL
from typing import List, Dict, Tuple

dici_onto = Namespace("https://digicities.info/ontology#")


class ComponentMixin:
    """Mixin for component operations"""

    # =================== Query Operations ===================

    def explore_components(self, extension_filename: str) -> List[Dict[str, str]]:
        """Get all components (subclasses of Component)"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?component ?label WHERE {
              ?component rdfs:subClassOf* dici_onto:Component .
              OPTIONAL { ?component rdfs:label ?label. }
            }
            """
            results = g.query(query)
            table_data = []
            for row in results:
                table_data.append({
                    "class": str(row.component),
                    "label": str(row.label) if row.label else ""
                })
            return table_data
        except Exception as e:
            print(f"Error exploring components: {e}")
            return []

    def get_component_range(self, extension_filename: str, component_uri: str) -> List[Dict[str, str]]:
        """Get the range of properties for a component"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?range ?rangeLabel WHERE {{
              ?property rdfs:domain <{component_uri}> .
              ?property rdfs:range ?range .
              OPTIONAL {{ ?range rdfs:label ?rangeLabel. }}
            }}
            """
            results = g.query(query)
            range_data = []
            for row in results:
                range_data.append({
                    "range": str(row.range),
                    "label": str(row.rangeLabel) if row.rangeLabel else ""
                })
            return range_data
        except Exception as e:
            print(f"Error getting component range: {e}")
            return []

    def explore_properties(self, extension_filename: str) -> List[Dict[str, str]]:
        """Get all object properties (subProperties of hasAttribute)"""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []

            query = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?property ?label WHERE {
              ?property rdfs:subPropertyOf* dici_onto:hasAttribute .
              ?property a owl:ObjectProperty .
              OPTIONAL { ?property rdfs:label ?label. }
            }
            """

            results = g.query(query)
            properties = []
            for row in results:
                properties.append({
                    "class": str(row["property"]),
                    "label": str(row["label"]) if "label" in row and row["label"] is not None else ""
                })
            return properties
        except Exception as e:
            print(f"Error exploring properties: {e}")
            return []

    # =================== Component CRUD Operations ===================

    def add_component(self, extension_filename: str, new_component_label: str,
                      parent_component: str) -> Tuple[bool, str]:
        """Add a new component to the ontology"""
        try:
            new_component = "".join(new_component_label.split())

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            parent_local = parent_component.split('#')[-1]
            parent_component_uri = dici_onto[parent_local]

            new_component_uri = dici_onto[new_component]
            ext_graph.add((new_component_uri, RDF.type, OWL.Class))
            ext_graph.add((new_component_uri, RDFS.subClassOf, parent_component_uri))
            ext_graph.add((new_component_uri, RDFS.label, Literal(new_component_label)))

            self.create_component_attribute_hierarchy(ext_graph, new_component, parent_component)

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Component added successfully"
        except Exception as e:
            return False, f"Error adding component: {str(e)}"

    def remove_component(self, extension_filename: str, component_uri: str) -> Tuple[bool, str]:
        """Remove a component and all its associated triples"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            component_ref = URIRef(component_uri)

            # Remove all triples where this component is the subject
            triples_to_remove = list(ext_graph.triples((component_ref, None, None)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            # Remove all triples where this component is the object
            triples_to_remove = list(ext_graph.triples((None, None, component_ref)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            # Remove associated properties
            component_local = component_uri.split('#')[-1]
            property_uri = dici_onto["has" + component_local + "Attribute"]
            triples_to_remove = list(ext_graph.triples((property_uri, None, None)))
            for triple in triples_to_remove:
                ext_graph.remove(triple)

            # Remove specific attribute properties
            all_triples = list(ext_graph.triples((None, None, None)))
            for subject, predicate, obj in all_triples:
                if str(predicate).startswith(str(dici_onto) + "has" + component_local):
                    ext_graph.remove((subject, predicate, obj))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Component removed successfully"
        except Exception as e:
            return False, f"Error removing component: {str(e)}"

    def change_component_parent(self, extension_filename: str, component_uri: str,
                                new_parent_uri: str) -> Tuple[bool, str]:
        """Change the parent class of a component and update the entire attribute hierarchy"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            component_ref = URIRef(component_uri)
            new_parent_ref = URIRef(new_parent_uri)
            component_local = component_uri.split('#')[-1]

            # Get all attributes currently linked to this component and its descendants
            component_attributes = self.get_component_and_descendant_attributes(ext_graph, component_local)

            # Remove old component hierarchy
            self.remove_existing_subclass_relationships(ext_graph, component_ref)

            # Add new parent relationship
            ext_graph.add((component_ref, RDFS.subClassOf, new_parent_ref))

            # Create new attribute hierarchy for the new parent chain
            self.create_component_attribute_hierarchy(ext_graph, component_local, new_parent_ref)

            # Transfer all attributes to the new hierarchy
            self.transfer_attributes_to_new_hierarchy(ext_graph, component_attributes, component_local)

            # Update property hierarchy
            self.update_property_hierarchy(ext_graph, component_local, new_parent_ref)

            # Clean up orphaned attribute classes
            self.cleanup_orphaned_attribute_classes(ext_graph)

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, "Component parent changed and attribute hierarchy updated successfully"
        except Exception as e:
            return False, f"Error changing component parent: {str(e)}"

    # =================== Component Helper Functions ===================

    def create_component_attribute_hierarchy(self, graph: rdflib.Graph,
                                             new_component_local: str,
                                             parent_component_uri: str):
        """Create the complete attribute hierarchy for a new component"""
        component_chain = self.get_component_hierarchy_chain(graph, parent_component_uri)
        component_chain.append(new_component_local)

        previous_attribute_class = dici_onto["ComponentAttribute"]

        for component_local in component_chain:
            current_attribute_class = dici_onto[component_local + "Attribute"]

            attribute_exists = False
            for triple in graph.triples((current_attribute_class, RDF.type, OWL.Class)):
                attribute_exists = True
                break

            if not attribute_exists:
                graph.add((current_attribute_class, RDF.type, OWL.Class))
                graph.add((current_attribute_class, RDFS.subClassOf, previous_attribute_class))
                graph.add((current_attribute_class, RDFS.label, Literal(component_local + " Attribute")))

            previous_attribute_class = current_attribute_class

        # Create the property for the new component
        new_property = dici_onto["has" + new_component_local + "Attribute"]
        parent_local = str(parent_component_uri).split('#')[-1]
        parent_property = dici_onto["has" + parent_local + "Attribute"]

        graph.add((new_property, RDF.type, OWL.ObjectProperty))
        graph.add((new_property, RDFS.subPropertyOf, parent_property))
        graph.add((new_property, RDFS.domain, dici_onto[new_component_local]))

    def get_component_hierarchy_chain(self, graph: rdflib.Graph,
                                      component_uri: str) -> List[str]:
        """Get the complete hierarchy chain from the first child of Component down to the given component"""
        hierarchy = []
        current_component = component_uri

        while current_component:
            current_local = str(current_component).split('#')[-1]

            if current_local == "Component":
                break

            hierarchy.insert(0, current_local)

            parent_found = False
            for triple in graph.triples((current_component, RDFS.subClassOf, None)):
                parent_component = triple[2]
                parent_local = str(parent_component).split('#')[-1]

                if str(parent_component).startswith(str(dici_onto)):
                    current_component = parent_component
                    parent_found = True
                    break

            if not parent_found:
                break

        return hierarchy

    def get_component_and_descendant_attributes(self, graph: rdflib.Graph,
                                                component_local: str) -> List[Dict]:
        """Get all attributes linked to this component and all its descendant components"""
        attributes = []

        component_attribute_class = dici_onto[component_local + "Attribute"]
        for subj, pred, obj in graph.triples((None, RDFS.subClassOf, component_attribute_class)):
            subj_local = str(subj).split('#')[-1]
            if not subj_local.endswith("Attribute") or subj_local == component_local + "Attribute":
                continue
            attributes.append({
                'uri': str(subj),
                'local': subj_local,
                'component': component_local
            })

        descendant_components = self.get_descendant_components(graph, component_local)
        for desc_component in descendant_components:
            desc_attribute_class = dici_onto[desc_component + "Attribute"]
            for subj, pred, obj in graph.triples((None, RDFS.subClassOf, desc_attribute_class)):
                subj_local = str(subj).split('#')[-1]
                if not subj_local.endswith("Attribute") or subj_local == desc_component + "Attribute":
                    continue
                attributes.append({
                    'uri': str(subj),
                    'local': subj_local,
                    'component': desc_component
                })

        return attributes

    def get_descendant_components(self, graph: rdflib.Graph, component_local: str) -> List[str]:
        """Get all components that are descendants of the given component"""
        descendants = []
        component_uri = dici_onto[component_local]

        for subj, pred, obj in graph.triples((None, RDFS.subClassOf, component_uri)):
            subj_local = str(subj).split('#')[-1]
            if str(subj).startswith(str(dici_onto)) and subj_local != component_local:
                descendants.append(subj_local)
                descendants.extend(self.get_descendant_components(graph, subj_local))

        return list(set(descendants))

    def remove_existing_subclass_relationships(self, graph: rdflib.Graph, component_ref: URIRef):
        """Remove existing subClassOf relationships for the component"""
        triples_to_remove = list(graph.triples((component_ref, RDFS.subClassOf, None)))
        for triple in triples_to_remove:
            graph.remove(triple)

    def transfer_attributes_to_new_hierarchy(self, graph: rdflib.Graph,
                                             attributes: List[Dict],
                                             moved_component_local: str):
        """Transfer all attributes to the new hierarchy"""
        for attr in attributes:
            attr_uri = URIRef(attr['uri'])
            attr_component = attr['component']

            old_relationships = list(graph.triples((attr_uri, RDFS.subClassOf, None)))
            for triple in old_relationships:
                obj_local = str(triple[2]).split('#')[-1]
                if obj_local.endswith("Attribute"):
                    graph.remove(triple)

            new_component_attribute_class = dici_onto[attr_component + "Attribute"]
            graph.add((attr_uri, RDFS.subClassOf, new_component_attribute_class))

    def update_property_hierarchy(self, graph: rdflib.Graph,
                                  component_local: str,
                                  new_parent_ref: URIRef):
        """Update the property hierarchy for the moved component"""
        new_parent_local = str(new_parent_ref).split('#')[-1]

        old_property = dici_onto["has" + component_local + "Attribute"]
        old_relationships = list(graph.triples((old_property, RDFS.subPropertyOf, None)))
        for triple in old_relationships:
            graph.remove(triple)

        new_parent_property = dici_onto["has" + new_parent_local + "Attribute"]
        graph.add((old_property, RDFS.subPropertyOf, new_parent_property))

    def cleanup_orphaned_attribute_classes(self, graph: rdflib.Graph):
        """Remove attribute classes that no longer have any subclasses or instances"""
        attribute_classes = []
        for subj, pred, obj in graph.triples((None, RDF.type, OWL.Class)):
            subj_local = str(subj).split('#')[-1]
            if subj_local.endswith("Attribute") and subj_local not in ["Attribute", "ComponentAttribute"]:
                attribute_classes.append(subj)

        classes_to_remove = []
        for attr_class in attribute_classes:
            attr_class_local = str(attr_class).split('#')[-1]

            base_component_name = attr_class_local.replace("Attribute", "")
            component_exists = False
            for subj, pred, obj in graph.triples((dici_onto[base_component_name], RDF.type, OWL.Class)):
                component_exists = True
                break

            if component_exists:
                continue

            has_subclasses = False
            for subj, pred, obj in graph.triples((None, RDFS.subClassOf, attr_class)):
                has_subclasses = True
                break

            has_property_references = False
            for subj, pred, obj in graph.triples((None, RDFS.range, attr_class)):
                has_property_references = True
                break

            if not has_subclasses and not has_property_references:
                classes_to_remove.append(attr_class)

        for class_to_remove in classes_to_remove:
            triples_to_remove = list(graph.triples((class_to_remove, None, None)))
            for triple in triples_to_remove:
                graph.remove(triple)