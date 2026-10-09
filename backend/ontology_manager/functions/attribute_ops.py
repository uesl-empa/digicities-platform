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

from backend.ontology_kinds import AttributeKind, is_attribute_class
from backend.ontology_scaffold import (
    attributes_of, categories as scaffold_categories, ensure_scaffold, link_predicates,
    local_name, own_category, own_general_predicate, specific_predicates_of,
)

dici_onto = Namespace("https://digicities.info/ontology#")


# The Ontology Manager's attribute type strings (its form labels) and the kind
# each one is. Parsed once here; the code below dispatches on the kind and
# files the new class under the kind's core class.
OM_TYPE_KIND = {
    "Physical": AttributeKind.PHYSICAL,
    "Simple Cost": AttributeKind.SIMPLE_COST,
    "Unit-Based Cost": AttributeKind.UNIT_BASED_COST,
    "Curve": AttributeKind.CURVE,
    "Categorical": AttributeKind.CATEGORICAL,
    "Geospatial": AttributeKind.GEOSPATIAL,
    "CustomPhysicalRatio": AttributeKind.CUSTOM_PHYSICAL_RATIO,
    "Event": AttributeKind.EVENT,
    "SimpleValue": AttributeKind.SIMPLE_VALUE,
}

# Kinds ``explore_attributes_by_type`` narrows to; any other type lists every
# attribute class.
_BY_TYPE_KINDS = (
    AttributeKind.SIMPLE_COST, AttributeKind.UNIT_BASED_COST, AttributeKind.CATEGORICAL,
    AttributeKind.CUSTOM_PHYSICAL_RATIO, AttributeKind.EVENT, AttributeKind.SIMPLE_VALUE,
)

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

            try:
                kind = AttributeKind(attribute_type)
            except ValueError:
                kind = None
            ontology_class = kind.class_uri if kind in _BY_TYPE_KINDS else dici_onto.Attribute

            query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dici_onto: <https://digicities.info/ontology#>
            SELECT DISTINCT ?attribute ?label WHERE {{
              ?attribute rdfs:subClassOf* <{ontology_class}> .
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
        """The attributes linked to a component: the ranges of its specific
        predicates (:func:`backend.ontology_scaffold.attributes_of`)."""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []
            attributes = []
            for attribute in attributes_of(g, URIRef(component_uri)):
                label = g.value(attribute, RDFS.label)
                attributes.append({"class": str(attribute),
                                   "label": str(label) if label else ""})
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
            kind = OM_TYPE_KIND.get(attribute_type)

            # Validate type-specific requirements
            if kind in (AttributeKind.PHYSICAL, AttributeKind.GEOSPATIAL,
                        AttributeKind.UNIT_BASED_COST) and not qudt_unit:
                return False, f"QUDT unit is required for {attribute_type} attributes"

            if kind is AttributeKind.CURVE and (not qudt_unit or not y_qudt_unit):
                return False, "Both X and Y axis units are required for Curve attributes"

            if kind is AttributeKind.CUSTOM_PHYSICAL_RATIO and (not x_unit or not y_qudt_unit):
                return False, "Both X and Y units are required for CustomPhysicalRatio"

            if kind is AttributeKind.EVENT and not temporal_precision:
                return False, "Temporal precision is required for Event attributes"

            from ..naming import check_class_name, class_name
            from .. import hierarchy

            new_attribute = class_name(attribute_label)
            core_mod = extension_filename == "CORE_ONTOLOGY_MODIFICATION"

            if core_mod:
                if self.use_nextcloud:
                    return False, "Cannot modify core ontology in NextCloud mode (read-only)"
                ext_graph = self.load_core_ontology()
            else:
                ext_graph = self.load_extension(extension_filename)

            if not parent_property and kind is None:
                return False, (f"Unknown attribute type `{attribute_type}` — one of "
                               f"{', '.join(sorted(OM_TYPE_KIND))}")
            chk = check_class_name(new_attribute,
                                   core=None if core_mod else self.load_core_ontology(),
                                   existing=hierarchy.classes(ext_graph), label=attribute_label)
            if not chk.ok:
                return False, f"Cannot add `{new_attribute}`: {'; '.join(chk.errors)}"

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
                ext_graph.add((new_attribute_uri, RDFS.subClassOf, kind.class_uri))

            # Handle different attribute types with their specific properties
            if kind in (AttributeKind.PHYSICAL, AttributeKind.GEOSPATIAL):
                default_unit = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultUnit, default_unit))

            elif kind is AttributeKind.UNIT_BASED_COST:
                selected_unit_uri = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultUnit, selected_unit_uri))
                restriction_bnode = BNode()
                ext_graph.add((restriction_bnode, RDF.type, OWL.Restriction))
                ext_graph.add((restriction_bnode, OWL.onProperty, URIRef("http://qudt.org/schema/qudt/unit")))
                ext_graph.add((restriction_bnode, OWL.hasValue, selected_unit_uri))
                ext_graph.add((new_attribute_uri, RDFS.subClassOf, restriction_bnode))

            elif kind is AttributeKind.CURVE:
                default_units_bnode = BNode()
                x_unit_uri = URIRef("http://qudt.org/vocab/unit/" + qudt_unit)
                y_unit_uri = URIRef("http://qudt.org/vocab/unit/" + y_qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultUnit, default_units_bnode))
                ext_graph.add((default_units_bnode, dici_onto.xUnit, x_unit_uri))
                ext_graph.add((default_units_bnode, dici_onto.yUnit, y_unit_uri))

            elif kind is AttributeKind.CUSTOM_PHYSICAL_RATIO:
                ratio_units_bnode = BNode()
                x_unit_uri = URIRef("http://qudt.org/vocab/unit/" + x_unit)
                y_unit_uri = URIRef("http://qudt.org/vocab/unit/" + y_qudt_unit)
                ext_graph.add((new_attribute_uri, dici_onto.hasRatioUnits, ratio_units_bnode))
                ext_graph.add((ratio_units_bnode, dici_onto.numeratorUnit, x_unit_uri))
                ext_graph.add((ratio_units_bnode, dici_onto.denominatorUnit, y_unit_uri))

            elif kind is AttributeKind.EVENT:
                precision_uri = dici_onto[temporal_precision]
                ext_graph.add((new_attribute_uri, dici_onto.hasDefaultTemporalPrecision, precision_uri))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            note = f" Note: {'; '.join(chk.warnings)}." if chk.warnings else ""
            return True, f"Attribute `{new_attribute}` added.{note}"
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

    # Canonical base attribute value-types: the core classes of these kinds.
    BASE_ATTRIBUTE_TYPES = {k.class_uri for k in (
        AttributeKind.PHYSICAL, AttributeKind.SIMPLE_COST, AttributeKind.UNIT_BASED_COST,
        AttributeKind.CURVE, AttributeKind.CATEGORICAL, AttributeKind.GEOSPATIAL,
        AttributeKind.CUSTOM_PHYSICAL_RATIO, AttributeKind.EVENT,
        AttributeKind.SIMPLE_VALUE, AttributeKind.RESOURCE,
    )}
    # Of those, the ones that carry a dici_onto:hasDefaultUnit.
    _UNIT_BEARING_BASE_TYPES = {k.class_uri for k in (
        AttributeKind.PHYSICAL, AttributeKind.GEOSPATIAL, AttributeKind.UNIT_BASED_COST,
        AttributeKind.CURVE, AttributeKind.CUSTOM_PHYSICAL_RATIO,
    )}

    def set_attribute_base_type(self, extension_filename: str, attribute: str,
                                base_type: str) -> Tuple[bool, str]:
        """Change an existing attribute class's base value-type.

        The repeatable, backend-driven way to reclassify an attribute (e.g. a
        ``WeatherEPW`` that was wrongly declared a ``PhysicalAttribute`` becomes a
        ``ResourceAttribute`` file reference) rather than hand-editing TTL. Swaps
        the ``rdfs:subClassOf`` from whichever base type it currently has to
        ``base_type``, and drops a now-meaningless ``hasDefaultUnit`` when moving
        to a unit-less type. Mirrors :meth:`set_default_unit`'s load/save/export
        flow so the temp graph and per-workspace export stay in sync.

        Args:
            extension_filename: the extension to edit, or ``CORE_ONTOLOGY_MODIFICATION``.
            attribute: the attribute class — full IRI or local name.
            base_type: one of :attr:`BASE_ATTRIBUTE_TYPES` (IRI or local name).

        Returns:
            ``(ok, message)``.
        """
        try:
            base_local = base_type.split('#')[-1].split('/')[-1]
            base_uri = dici_onto[base_local]
            if base_uri not in self.BASE_ATTRIBUTE_TYPES:
                known = sorted(str(u)[len(str(dici_onto)):] for u in self.BASE_ATTRIBUTE_TYPES)
                return False, (f"'{base_local}' is not a known base attribute type "
                               f"(one of: {', '.join(known)})")

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

            # Swap the base value-type: drop subClassOf to any known base type,
            # leaving domain/other superclasses untouched, then add the new one.
            for parent in list(ext_graph.objects(attr_uri, RDFS.subClassOf)):
                if parent in self.BASE_ATTRIBUTE_TYPES:
                    ext_graph.remove((attr_uri, RDFS.subClassOf, parent))
            ext_graph.add((attr_uri, RDFS.subClassOf, base_uri))

            # Units are meaningless for non-unit-bearing types — remove any default.
            if base_uri not in self._UNIT_BEARING_BASE_TYPES:
                for u in list(ext_graph.objects(attr_uri, dici_onto.hasDefaultUnit)):
                    ext_graph.remove((attr_uri, dici_onto.hasDefaultUnit, u))

            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                self.save_core_ontology(ext_graph)
                self.update_temp_and_export_core_mod()
            else:
                self.save_extension(extension_filename, ext_graph)
                self.update_temp_and_export(extension_filename)

            return True, f"Base type for '{local}' set to {base_local}"
        except Exception as e:
            return False, f"Error setting base type: {str(e)}"

    def remove_attribute(self, extension_filename: str, attribute_uri: str) -> Tuple[bool, str]:
        """Remove an attribute, every triple that mentions it and the specific
        predicates that link it to a component (found by their domain, range
        and general predicate, never by name)."""
        try:
            ext_graph = self._edit_graph(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)
            attribute_ref = URIRef(attribute_uri)

            # The links to this attribute, collected before its range triples go.
            owned = set()
            for prop in set(view.subjects(RDFS.range, attribute_ref)):
                for dom in set(view.objects(prop, RDFS.domain)):
                    if prop in specific_predicates_of(view, dom):
                        owned.add(prop)

            for triple in list(ext_graph.triples((attribute_ref, None, None))):
                ext_graph.remove(triple)
            for triple in list(ext_graph.triples((None, None, attribute_ref))):
                ext_graph.remove(triple)
            for prop in owned:
                for triple in list(ext_graph.triples((prop, None, None))):
                    ext_graph.remove(triple)
                for triple in list(ext_graph.triples((None, prop, None))):
                    ext_graph.remove(triple)

            self._persist(extension_filename, ext_graph)
            return True, "Attribute removed successfully"
        except Exception as e:
            return False, f"Error removing attribute: {str(e)}"

    def link_attribute(self, extension_filename: str, component: str,
                       attribute_property: str) -> Tuple[bool, str]:
        """Link an attribute to a component: the component gets its scaffold if
        it has none (:func:`backend.ontology_scaffold.ensure_scaffold`), the
        attribute goes under the component's category, and one specific
        predicate ``has<Component><Attribute>Attribute`` (under the general
        predicate, domain the component, range the attribute) states the link.
        The general predicate keeps its category as its only range."""
        try:
            ext_graph = self._edit_graph(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)
            component_ref = URIRef(component)
            attribute_ref = URIRef(attribute_property)
            if not is_attribute_class(view, attribute_ref):
                return False, f"`{local_name(attribute_ref)}` is not an attribute class"

            general, category = ensure_scaffold(view, ext_graph, component_ref)
            if (attribute_ref, RDFS.subClassOf, category) not in view:
                ext_graph.add((attribute_ref, RDFS.subClassOf, category))

            if not link_predicates(view, component_ref, attribute_ref):
                specific = dici_onto[f"has{local_name(component_ref)}"
                                     f"{local_name(attribute_ref)}Attribute"]
                if (specific, None, None) in view:
                    return False, (f"`{local_name(specific)}` already exists and does not "
                                   f"link `{local_name(component_ref)}` to "
                                   f"`{local_name(attribute_ref)}`")
                ext_graph.add((specific, RDF.type, OWL.ObjectProperty))
                ext_graph.add((specific, RDFS.subPropertyOf, general))
                ext_graph.add((specific, RDFS.domain, component_ref))
                ext_graph.add((specific, RDFS.range, attribute_ref))

            self._persist(extension_filename, ext_graph)
            return True, "Attribute linked to component successfully"
        except Exception as e:
            return False, f"Error linking attribute: {str(e)}"

    def remove_attribute_link(self, extension_filename: str, component_uri: str,
                              attribute_uri: str) -> Tuple[bool, str]:
        """Undo ``link_attribute``: remove the specific predicate(s) linking the
        component to the attribute, and the attribute's place under the
        component's category when no link to it is left and it keeps another
        superclass (its value kind)."""
        try:
            ext_graph = self._edit_graph(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)
            component_ref = URIRef(component_uri)
            attribute_ref = URIRef(attribute_uri)

            found = link_predicates(view, component_ref, attribute_ref)
            general = own_general_predicate(view, component_ref)
            # The form an older Ontology Manager wrote: the attribute as a range
            # of the general predicate.
            legacy = general is not None and (general, RDFS.range, attribute_ref) in ext_graph
            if not found and not legacy:
                return False, (f"`{local_name(attribute_ref)}` is not linked to "
                               f"`{local_name(component_ref)}` in this extension")
            category = own_category(view, component_ref)
            for prop in found:
                for triple in list(ext_graph.triples((prop, None, None))):
                    ext_graph.remove(triple)
                for triple in list(ext_graph.triples((None, None, prop))):
                    ext_graph.remove(triple)
            if legacy:
                ext_graph.remove((general, RDFS.range, attribute_ref))
            if category is not None and (attribute_ref, RDFS.subClassOf, category) in ext_graph:
                others = set(view.objects(attribute_ref, RDFS.subClassOf)) - {category}
                if others:
                    ext_graph.remove((attribute_ref, RDFS.subClassOf, category))

            self._persist(extension_filename, ext_graph)
            return True, "Attribute link removed successfully"
        except Exception as e:
            return False, f"Error removing attribute link: {str(e)}"

    # =================== Category Management ===================

    def _category_classes(self, g: rdflib.Graph) -> set:
        """The attribute categories: ``Attribute``, its direct subclasses (the
        value kinds and ``ComponentAttribute``) and every component's own
        category (:func:`backend.ontology_scaffold.categories`)."""
        out = {dici_onto.Attribute}
        out |= {c for c in g.subjects(RDFS.subClassOf, dici_onto.Attribute)
                if isinstance(c, URIRef)}
        out |= set(scaffold_categories(g))
        return out

    def get_attribute_categories(self, extension_filename: str) -> List[Dict[str, str]]:
        """Get all attribute categories that carry a label."""
        try:
            g = self._load_temp_graph(extension_filename)
            if g is None:
                return []
            categories = []
            for category in sorted(self._category_classes(g)):
                for label in g.objects(category, RDFS.label):
                    categories.append({"class": str(category), "label": str(label)})
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
            cats = self._category_classes(g)
            categories = []
            for category in sorted(set(g.objects(URIRef(attribute_uri), RDFS.subClassOf)) & cats):
                label = g.value(category, RDFS.label)
                categories.append({"class": str(category), "label": str(label) if label else ""})
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
            from ..naming import class_name
            individual_id = class_name(individual_label)
            if not individual_id:
                return False, f"`{individual_label}` has no letters or digits to name a value by"

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