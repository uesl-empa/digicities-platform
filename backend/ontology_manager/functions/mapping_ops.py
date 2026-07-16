# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Mapping and GraphDB Operations.

All workspace file I/O goes through the storage helpers on OntologyBase
(`_read_graph`/`_read_text`/`_write_text`/`_list_ttl` + `self.storage`), so this
mixin works identically on local disk and NextCloud with no backend branching.
"""

import rdflib
from rdflib import Namespace, URIRef
from typing import List, Dict, Tuple, Optional, Any

dici_onto = Namespace("https://digicities.info/ontology#")


class MappingMixin:
    """Mixin for mapping and GraphDB operations"""

    # =================== Mapping Operations ===================

    def list_mapping_inputs(self) -> List[str]:
        """List all .ttl mapping input files"""
        return self._list_ttl(self.MAPPING_INPUT_PATH)

    def get_mapping_classes(self, mapping_filename: str) -> List[Dict[str, str]]:
        """Get classes from a mapping file"""
        try:
            g = self._read_graph(f"{self.MAPPING_INPUT_PATH}/{mapping_filename}")
            query = """
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?class WHERE {
              { ?class a owl:Class . } UNION { ?class a rdfs:Class . }
            }
            """
            classes = []
            for row in g.query(query):
                full_uri = str(row["class"])
                local = full_uri.split("#")[-1] if "#" in full_uri else full_uri.split("/")[-1]
                classes.append({"full": full_uri, "local": local})
            return classes
        except Exception as e:
            print(f"Error getting mapping classes: {e}")
            return []

    def get_mapping_properties(self, mapping_filename: str) -> List[Dict[str, str]]:
        """Get object properties from a mapping file"""
        try:
            g = self._read_graph(f"{self.MAPPING_INPUT_PATH}/{mapping_filename}")
            query = """
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT DISTINCT ?property WHERE {
              ?property a owl:ObjectProperty .
            }
            """
            properties = []
            for row in g.query(query):
                full_uri = str(row["property"])
                local = full_uri.split("#")[-1] if "#" in full_uri else full_uri.split("/")[-1]
                properties.append({"full": full_uri, "local": local})
            return properties
        except Exception as e:
            print(f"Error getting mapping properties: {e}")
            return []

    def _get_mapping_namespace(self, mapping_filename: str) -> Optional[str]:
        """Helper to extract namespace from mapping file"""
        try:
            g = self._read_graph(f"{self.MAPPING_INPUT_PATH}/{mapping_filename}")
            for prefix, ns in g.namespaces():
                if prefix not in ["rdf", "rdfs", "owl", "xsd", "skos"]:
                    return str(ns)
            return None
        except Exception as e:
            print(f"Error getting mapping namespace: {e}")
            return None

    def _save_mapping(self, chosen_uri: str, predicate: URIRef, obj: URIRef,
                      mapping_ns: str, output_path: str) -> None:
        """Append one mapping triple to the output graph and persist it."""
        out_graph = self._read_graph(output_path)
        out_graph.add((URIRef(chosen_uri), predicate, obj))
        out_graph.bind("dici_onto", dici_onto)
        out_graph.bind("mapping", mapping_ns)
        self._write_text(output_path, out_graph.serialize(format="ttl"))

    def map_component(self, chosen_component: str, linkage_relation: str,
                      mapping_class: str, mapping_filename: str) -> Tuple[bool, str]:
        """Map a component to a mapping class"""
        try:
            mapping_ns = self._get_mapping_namespace(mapping_filename)
            if not mapping_ns:
                return False, "Mapping namespace not found"

            predicate = self._class_linkage_predicate(linkage_relation)
            if predicate is None:
                return False, "Invalid linkage relation"

            output_filename = mapping_filename.replace(".ttl", "") + "_2_dici_onto.ttl"
            output_path = f"{self.MAPPING_OUTPUT_PATH}/{output_filename}"
            self._save_mapping(chosen_component, predicate, URIRef(mapping_ns + mapping_class),
                               mapping_ns, output_path)
            return True, "Component mapping saved successfully"
        except Exception as e:
            return False, f"Error mapping component: {str(e)}"

    def map_attribute(self, chosen_attribute: str, linkage_relation: str,
                      mapping_class: str, mapping_filename: str) -> Tuple[bool, str]:
        """Map an attribute to a mapping class"""
        try:
            mapping_ns = self._get_mapping_namespace(mapping_filename)
            if not mapping_ns:
                return False, "Mapping namespace not found"

            predicate = self._class_linkage_predicate(linkage_relation)
            if predicate is None:
                return False, "Invalid linkage relation"

            output_filename = mapping_filename.replace(".ttl", "") + "_2_dici_onto.ttl"
            output_path = f"{self.MAPPING_OUTPUT_PATH}/{output_filename}"
            self._save_mapping(chosen_attribute, predicate, URIRef(mapping_ns + mapping_class),
                               mapping_ns, output_path)
            return True, "Attribute mapping saved successfully"
        except Exception as e:
            return False, f"Error mapping attribute: {str(e)}"

    def map_property(self, chosen_property: str, linkage_relation: str,
                     mapping_property: str, mapping_filename: str) -> Tuple[bool, str]:
        """Map a property to a mapping property"""
        try:
            mapping_ns = self._get_mapping_namespace(mapping_filename)
            if not mapping_ns:
                return False, "Mapping namespace not found"

            if linkage_relation == "owl:equivalentProperty":
                predicate = URIRef("http://www.w3.org/2002/07/owl#equivalentProperty")
            elif linkage_relation == "rdfs:subPropertyOf":
                predicate = URIRef("http://www.w3.org/2000/01/rdf-schema#subPropertyOf")
            elif linkage_relation == "skos:closeMatch":
                predicate = URIRef("http://www.w3.org/2004/02/skos/core#closeMatch")
            else:
                return False, "Invalid linkage relation"

            output_filename = mapping_filename.replace(".ttl", "") + "_2_dici_onto.ttl"
            output_path = f"{self.MAPPING_OUTPUT_PATH}/{output_filename}"
            self._save_mapping(chosen_property, predicate, URIRef(mapping_ns + mapping_property),
                               mapping_ns, output_path)
            return True, "Property mapping saved successfully"
        except Exception as e:
            return False, f"Error mapping property: {str(e)}"

    @staticmethod
    def _class_linkage_predicate(linkage_relation: str) -> Optional[URIRef]:
        if linkage_relation == "owl:equivalentClass":
            return URIRef("http://www.w3.org/2002/07/owl#equivalentClass")
        if linkage_relation == "rdfs:subClassOf":
            return URIRef("http://www.w3.org/2000/01/rdf-schema#subClassOf")
        if linkage_relation == "skos:closeMatch":
            return URIRef("http://www.w3.org/2004/02/skos/core#closeMatch")
        return None

    def get_property_mappings(self, mapping_filename: str) -> List[Dict[str, str]]:
        """Get all property mappings from the mapping output file"""
        try:
            output_filename = mapping_filename.replace(".ttl", "") + "_2_dici_onto.ttl"
            output_path = f"{self.MAPPING_OUTPUT_PATH}/{output_filename}"
            if not self.storage.exists(output_path):
                return []
            g = self._read_graph(output_path)

            query = """
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {
              ?subject ?predicate ?object .
              FILTER(?predicate IN (owl:equivalentProperty, rdfs:subPropertyOf, skos:closeMatch))
            }
            """
            mappings = []
            for row in g.query(query):
                mappings.append({
                    "subject": str(row.subject),
                    "predicate": str(row.predicate),
                    "object": str(row.object)
                })
            return mappings
        except Exception as e:
            print(f"Error getting property mappings: {e}")
            return []

    def remove_property_mapping(self, mapping_filename: str, subject_uri: str,
                                predicate_uri: str, object_uri: str) -> Tuple[bool, str]:
        """Remove a specific property mapping"""
        try:
            output_filename = mapping_filename.replace(".ttl", "") + "_2_dici_onto.ttl"
            output_path = f"{self.MAPPING_OUTPUT_PATH}/{output_filename}"
            if not self.storage.exists(output_path):
                return False, "Mapping file not found"

            g = self._read_graph(output_path)
            g.remove((URIRef(subject_uri), URIRef(predicate_uri), URIRef(object_uri)))

            g.bind("dici_onto", dici_onto)
            for prefix, ns in g.namespaces():
                if prefix not in ["rdf", "rdfs", "owl", "xsd", "skos"]:
                    g.bind("mapping", ns)
                    break

            self._write_text(output_path, g.serialize(format="ttl"))
            return True, "Property mapping removed successfully"
        except Exception as e:
            return False, f"Error removing property mapping: {str(e)}"

    # =================== GraphDB Upload Operations ===================

    def get_export_info(self, extension_filename: str) -> Dict[str, Any]:
        """Get information about the export file."""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                export_filename = "dici_onto_core_mod_export.ttl"
            else:
                export_filename = extension_filename.replace(".ttl", "") + "_export.ttl"

            export_path = f"{self.EXPORTS_PATH}/{export_filename}"
            content = self._read_text(export_path)
            if content is None:
                return {
                    "exists": False,
                    "filename": export_filename,
                    "message": "Export file not found. Please load the extension first."
                }

            return {
                "exists": True,
                "filename": export_filename,
                "file_size": len(content.encode("utf-8")),
                "line_count": len(content.split("\n")),
                "modified_time": "Unknown"
            }
        except Exception as e:
            print(f"Error getting export info: {e}")
            import traceback
            traceback.print_exc()
            return {"exists": False, "filename": "", "message": f"Error: {str(e)}"}

    def get_export_ttl_content(self, extension_filename: str) -> Optional[str]:
        """Get the TTL content of the export file for uploading"""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                export_filename = "dici_onto_core_mod_export.ttl"
            else:
                export_filename = extension_filename.replace(".ttl", "") + "_export.ttl"

            content = self._read_text(f"{self.EXPORTS_PATH}/{export_filename}")
            if content is None:
                return None

            temp_graph = rdflib.Graph()
            temp_graph.parse(data=content, format="turtle")
            temp_graph.bind("dici_onto", dici_onto)
            return temp_graph.serialize(format="turtle")
        except Exception as e:
            print(f"Error getting export TTL content: {e}")
            return None

    def upload_to_graphdb(self, extension_filename: str, repository: str = None) -> Tuple[bool, Dict[str, Any]]:
        """Upload the ontology export to GraphDB's ontology named graph."""
        if not self.graphdb_client:
            return False, {"error": "GraphDB client not configured"}

        try:
            ttl_content = self.get_export_ttl_content(extension_filename)
            if not ttl_content:
                return False, {"error": "Could not read export file"}

            export_info = self.get_export_info(extension_filename)
            export_filename_str = export_info.get('filename', 'unknown')

            if not repository:
                repository = self.workspace_id

            graph_name = "<http://ontology_dici_onto>"
            self.graphdb_client.repository = repository

            self.graphdb_client.upload_ttl(
                ttl_str=ttl_content,
                graph_name=graph_name,
                replace_existing=True,
                split_size=100
            )

            self.set_active_extension(extension_filename)

            return True, {
                "message": f"Successfully uploaded to GraphDB repository '{repository}'",
                "export_file": export_filename_str,
                "repository": repository,
                "graph_name": graph_name
            }
        except Exception as e:
            print(f"Error uploading to GraphDB: {e}")
            import traceback
            traceback.print_exc()
            return False, {"error": str(e)}

    def get_repositories_from_graphdb(self) -> List[str]:
        """Get available GraphDB repositories"""
        if not self.graphdb_client:
            return []
        try:
            repositories = self.graphdb_client.get_repositories()
            return repositories if repositories else []
        except Exception as e:
            print(f"Error fetching repositories: {e}")
            return []
