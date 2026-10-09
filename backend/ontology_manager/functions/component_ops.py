# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Component Operations
File: components/ontology_manager/functions/components.py

Mixin for component CRUD operations and hierarchy management.
"""

import rdflib
from rdflib import Namespace, RDF, RDFS, Literal, URIRef, OWL
from typing import Iterable, List, Dict, Tuple

from backend.ontology_kinds import is_attribute_class, is_component_class
from backend.ontology_scaffold import (
    ensure_scaffold, local_name, own_category, own_general_predicate, specific_predicates_of,
)

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

    def component_tree(self, extension_filename: str, root: str = "Component",
                       depth: int = 6) -> Dict:
        """The class tree below ``root`` in core + this extension (``…Attribute``
        scaffolding left out) — what a user picks a parent from."""
        from .. import hierarchy
        return hierarchy.tree(self.merge_ontologies(extension_filename), root, depth)

    def suggest_parents(self, extension_filename: str, text: str, limit: int = 5) -> List[Dict]:
        """Existing component classes whose names, labels or examples share words with
        ``text`` — a shortlist to offer the user, never an automatic choice."""
        from .. import hierarchy
        return hierarchy.parent_candidates(self.merge_ontologies(extension_filename), text,
                                           limit=limit)

    def check_component_name(self, extension_filename: str, label: str) -> Dict:
        """The name a label would get and the verdict of the naming rules on it."""
        from ..naming import check_class_name, class_name
        from .. import hierarchy
        name = class_name(label)
        chk = check_class_name(name, core=self.load_core_ontology(),
                               existing=hierarchy.classes(self.load_extension(extension_filename)),
                               label=label)
        return {"name": name, "ok": chk.ok, "errors": chk.errors, "warnings": chk.warnings,
                "similar": [t for t, _h in chk.similar]}

    # =================== Component CRUD Operations ===================

    def add_component(self, extension_filename: str, new_component_label: str,
                      parent_component: str) -> Tuple[bool, str]:
        """Add a new component to the ontology, with its scaffold.

        The name is formed from the label by the shared naming rules
        (:mod:`backend.ontology_manager.naming`) and refused when it is not a
        valid class name, redefines a core term or already exists; the parent
        must be an existing component class (core or this extension). The new
        class gets its own category and general predicate under its parent's
        (:func:`backend.ontology_scaffold.ensure_scaffold`), and so does every
        ancestor that has none yet."""
        try:
            from ..naming import check_class_name, class_name
            from .. import hierarchy

            new_component = class_name(new_component_label)
            core_mod = extension_filename == self.CORE_TARGET
            ext_graph = self._edit_graph(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)

            core = self.load_core_ontology()
            chk = check_class_name(new_component, core=None if core_mod else core,
                                   existing=hierarchy.classes(ext_graph),
                                   label=new_component_label)
            if not chk.ok:
                return False, f"Cannot add `{new_component}`: {'; '.join(chk.errors)}"

            parent_ref = self._class_ref(parent_component)
            if not is_component_class(view, parent_ref):
                return False, (f"Cannot add `{new_component}`: its parent "
                               f"`{local_name(parent_ref)}` is not a component class in the "
                               "core ontology or this extension; add the parent first")

            new_component_uri = dici_onto[new_component]
            ext_graph.add((new_component_uri, RDF.type, OWL.Class))
            ext_graph.add((new_component_uri, RDFS.subClassOf, parent_ref))
            ext_graph.add((new_component_uri, RDFS.label, Literal(new_component_label)))
            ensure_scaffold(view, ext_graph, new_component_uri)

            self._persist(extension_filename, ext_graph)
            note = f" Note: {'; '.join(chk.warnings)}." if chk.warnings else ""
            return True, (f"Component `{new_component}` added under "
                          f"`{local_name(parent_ref)}`.{note}")
        except Exception as e:
            return False, f"Error adding component: {str(e)}"

    @staticmethod
    def _class_ref(term: str) -> URIRef:
        """A class given as a full IRI or a dici local name."""
        term = str(term)
        return URIRef(term) if "://" in term else dici_onto[term]

    def remove_component(self, extension_filename: str, component_uri: str) -> Tuple[bool, str]:
        """Remove a component, its own scaffold (general predicate, specific
        predicates and, once nothing hangs under it, its category) and every
        triple that mentions it."""
        try:
            ext_graph = self._edit_graph(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)
            component_ref = URIRef(component_uri)
            name = local_name(component_ref)

            # A class with subclasses can't go first: removing it would strip their
            # parent and leave them floating outside the tree. Proper sequence:
            # move or remove the subclasses, then the class.
            subs = sorted(local_name(s)
                          for s in ext_graph.subjects(RDFS.subClassOf, component_ref)
                          if s != component_ref and not is_attribute_class(view, s))
            if subs:
                return False, (f"Cannot remove `{name}`: "
                               f"{', '.join(f'`{s}`' for s in subs)} "
                               f"{'is' if len(subs) == 1 else 'are'} under it; move or remove "
                               f"{'it' if len(subs) == 1 else 'them'} first")

            # Its own scaffold, read BEFORE its triples go (the domain and range
            # triples are how it is found).
            general = own_general_predicate(view, component_ref)
            category = own_category(view, component_ref)
            owned = set(specific_predicates_of(view, component_ref))
            if general is not None:
                owned.add(general)

            for triple in list(ext_graph.triples((component_ref, None, None))):
                ext_graph.remove(triple)
            for triple in list(ext_graph.triples((None, None, component_ref))):
                ext_graph.remove(triple)
            for prop in owned:
                for triple in list(ext_graph.triples((prop, None, None))):
                    ext_graph.remove(triple)
                for triple in list(ext_graph.triples((None, None, prop))):
                    ext_graph.remove(triple)
            if category is not None:
                self.cleanup_orphaned_attribute_classes(ext_graph, [category])

            self._persist(extension_filename, ext_graph)
            return True, "Component removed successfully"
        except Exception as e:
            return False, f"Error removing component: {str(e)}"

    def change_component_parent(self, extension_filename: str, component_uri: str,
                                new_parent_uri: str) -> Tuple[bool, str]:
        """Move a component under another parent. Its category and general
        predicate move with it (under the new parent's), so its attributes and
        its subclasses' scaffolds follow without being touched."""
        try:
            ext_graph = self._edit_graph(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)
            component_ref = URIRef(component_uri)
            new_parent_ref = URIRef(new_parent_uri)
            component_local = local_name(component_ref)
            new_parent_local = local_name(new_parent_ref)

            # The proper sequence, checked on core + extension: the class is this
            # extension's own (a core class keeps its core parent; re-parenting it
            # here would give it two), the new parent exists, and the move doesn't
            # put the class under itself.
            from .. import hierarchy
            core = self.load_core_ontology()
            merged = core + ext_graph
            if extension_filename != self.CORE_TARGET:
                if component_local not in hierarchy.classes(ext_graph):
                    return False, (f"`{component_local}` is not a class of this extension"
                                   + (" (it is a core class)"
                                      if component_local in hierarchy.classes(core) else ""))
            if new_parent_local not in hierarchy.classes(merged):
                return False, (f"`{new_parent_local}` is not a class in the core ontology or "
                               "this extension; add it first")
            if hierarchy.would_cycle(merged, component_local, new_parent_local):
                return False, (f"`{new_parent_local}` is `{component_local}` itself or sits "
                               f"under it; a class can't be moved under its own subclass")

            for old in list(ext_graph.objects(component_ref, RDFS.subClassOf)):
                ext_graph.remove((component_ref, RDFS.subClassOf, old))
            ext_graph.add((component_ref, RDFS.subClassOf, new_parent_ref))
            ensure_scaffold(view, ext_graph, component_ref)

            self._persist(extension_filename, ext_graph)
            return True, "Component parent changed and attribute hierarchy updated successfully"
        except Exception as e:
            return False, f"Error changing component parent: {str(e)}"

    def rename_component(self, extension_filename: str, component_uri: str,
                         new_label: str) -> Tuple[bool, str]:
        """Rename a component of this extension and its own scaffold: the class,
        its category, its general predicate and its specific predicates, in
        every triple that mentions them. The scaffold is found by its triples
        and the new terms are minted by the same rule ``add_component`` and
        ``link_attribute`` use. The class takes ``new_label``; its category
        takes the generated label.

        Instance data in the replica is typed by the class name, so instances keep
        the old name until the replica is rebuilt from its workbook (the message
        says so)."""
        try:
            from ..naming import check_class_name, class_name
            from .. import hierarchy

            if extension_filename == self.CORE_TARGET:
                return False, "Core classes are renamed in the ontology repository, not here"
            ext_graph = self.load_extension(extension_filename)
            view = self._schema_view(extension_filename, ext_graph)
            core = self.load_core_ontology()
            old_uri = URIRef(component_uri)
            old = local_name(old_uri)
            new = class_name(new_label)
            ext_classes = hierarchy.classes(ext_graph)
            if old not in ext_classes:
                return False, (f"`{old}` is not a class of this extension"
                               + (" (it is a core class)" if old in hierarchy.classes(core)
                                  else ""))
            if new == old:
                return False, f"`{old}` already has that name"
            chk = check_class_name(new, core=core, existing=ext_classes, label=new_label)
            if not chk.ok:
                return False, f"Cannot rename `{old}` to `{new}`: {'; '.join(chk.errors)}"

            new_uri = dici_onto[new]
            rename = {old_uri: new_uri}
            general = own_general_predicate(view, old_uri)
            category = own_category(view, old_uri)
            if general is not None:
                rename[general] = dici_onto[f"has{new}Attribute"]
            if category is not None:
                rename[category] = dici_onto[f"{new}Attribute"]
            for p in specific_predicates_of(view, old_uri):
                for attr in view.objects(p, RDFS.range):
                    rename[p] = dici_onto[f"has{new}{local_name(attr)}Attribute"]
            clash = [local_name(t) for f, t in rename.items()
                     if f != t and (t, None, None) in view]
            if clash:
                return False, (f"Cannot rename `{old}` to `{new}`: "
                               f"{', '.join(f'`{c}`' for c in clash)} already exist")

            renamed = rdflib.Graph()
            for prefix, ns in ext_graph.namespaces():
                renamed.bind(prefix, ns)
            for s, p, o in ext_graph:
                if p == RDFS.label and s in (old_uri, category):
                    continue                      # set below
                renamed.add((rename.get(s, s), rename.get(p, p), rename.get(o, o)))
            renamed.add((new_uri, RDFS.label, Literal(new_label)))
            if category is not None:
                renamed.add((rename[category], RDFS.label, Literal(f"{new} Attribute")))

            self._persist(extension_filename, renamed)
            moved = len(rename) - 1
            return True, (f"Renamed `{old}` to `{new}`"
                          + (f" (and {moved} generated term{'s' if moved != 1 else ''})"
                             if moved else "")
                          + ". Instances in the replica keep the old type until the replica "
                            "is rebuilt from its workbook.")
        except Exception as e:
            return False, f"Error renaming component: {str(e)}"

    # =================== Component Helper Functions ===================

    def cleanup_orphaned_attribute_classes(self, graph: rdflib.Graph,
                                           candidates: Iterable[URIRef]):
        """Remove the given categories (of removed components) when no subclass
        and no property range still uses them."""
        for attr_class in candidates:
            if (attr_class, RDF.type, OWL.Class) not in graph:
                continue
            if any(graph.subjects(RDFS.subClassOf, attr_class)):
                continue
            if any(graph.subjects(RDFS.range, attr_class)):
                continue
            for triple in list(graph.triples((attr_class, None, None))):
                graph.remove(triple)
