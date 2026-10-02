# SPDX-License-Identifier: Apache-2.0
"""Service configuration: a model's settings live with its service, not on the
components, and the explorer can show them behind a toggle.

The wind forecaster's simulation file (wake model type, wake decay constant k,
turbulence intensity, simulation name) and its stream addresses are boundary
conditions of the model run. The onboarding agent used to make them a
`WindSimulationConfig` component, or attributes on the park. With core v0.5.0
they are `ConfigurationAttribute` values in a `ServiceConfiguration` profile
of the service, which `appliesTo` the park.

Deterministic: an in-memory rdflib dataset loaded with the REAL vendored core
stands in for the triplestore.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

rdflib = pytest.importorskip("rdflib")

from backend.graphdb.graphs import (  # noqa: E402
    CLASSES_AND_ATTRIBUTES_GRAPH,
    ONTOLOGY_GRAPH,
    SERVICES_GRAPH,
)

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data" / "ontology" / "dici_onto_core.ttl"
P = "https://digicities.info/proj/ws"

EXTENSION = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:WindPark a owl:Class ; rdfs:subClassOf dici_onto:Location ; rdfs:label "Wind Park" .
dici_onto:Roughness a owl:Class ; rdfs:subClassOf dici_onto:PhysicalAttribute ; rdfs:label "Roughness" .
dici_onto:hasWindParkRoughnessAttribute a owl:ObjectProperty ;
    rdfs:subPropertyOf dici_onto:hasAttribute .
dici_onto:ModelType a owl:Class ;
    rdfs:subClassOf dici_onto:CategoricalAttribute, dici_onto:ConfigurationAttribute ;
    rdfs:label "Model Type" .
dici_onto:WakeDecayConstant a owl:Class ;
    rdfs:subClassOf dici_onto:PhysicalAttribute, dici_onto:ConfigurationAttribute ;
    rdfs:label "Wake Decay Constant" .
dici_onto:OutputStream a owl:Class ;
    rdfs:subClassOf dici_onto:SimpleValueAttribute, dici_onto:ConfigurationAttribute ;
    rdfs:label "Output Stream" .
dici_onto:Bastankhah_PorteAgel_2014 a owl:NamedIndividual ; rdfs:label "Bastankhah_PorteAgel_2014" .
"""

REPLICA = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{P}/WindPark/Alkmaar> a dici_onto:WindPark ; rdfs:label "Alkmaar" ;
    dici_onto:hasWindParkRoughnessAttribute <{P}/WindPark/Alkmaar/Roughness> .
<{P}/WindPark/Alkmaar/Roughness> a dici_onto:Roughness, dici_onto:PhysicalAttribute ;
    qudt:value 1.0 .
<{P}/WindPark/Other> a dici_onto:WindPark ; rdfs:label "Other" .
"""

SERVICES = f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{P}/services/WindForecast> a dici_onto:Service ; rdfs:label "WindForecast" ;
    dici_onto:hasConfiguration <{P}/services/WindForecast/config/simulation_alkmaar>,
                               <{P}/services/WindForecast/config/runtime> .
<{P}/services/WindForecast/config/simulation_alkmaar> a dici_onto:ServiceConfiguration ;
    rdfs:label "simulation_alkmaar" ;
    dici_onto:appliesTo <{P}/WindPark/Alkmaar> ;
    dici_onto:hasConfigurationParameter <{P}/services/WindForecast/config/simulation_alkmaar/ModelType>,
        <{P}/services/WindForecast/config/simulation_alkmaar/WakeDecayConstant> .
<{P}/services/WindForecast/config/simulation_alkmaar/ModelType> a dici_onto:ModelType ;
    dici_onto:hasCategoricalValue dici_onto:Bastankhah_PorteAgel_2014 .
<{P}/services/WindForecast/config/simulation_alkmaar/WakeDecayConstant> a dici_onto:WakeDecayConstant ;
    qudt:value 0.0324555 .
<{P}/services/WindForecast/config/runtime> a dici_onto:ServiceConfiguration ;
    rdfs:label "runtime" ;
    dici_onto:hasConfigurationParameter <{P}/services/WindForecast/config/runtime/OutputStream> .
<{P}/services/WindForecast/config/runtime/OutputStream> a dici_onto:OutputStream ;
    dici_onto:hasAttributeValue "windforecast.eolica.Alkmaar" .
"""


class _Client:
    """Minimal stand-in for the triplestore client: same query contract."""

    def __init__(self):
        from rdflib.plugins import sparql
        sparql.SPARQL_LOAD_GRAPHS = False
        self.ds = rdflib.Dataset()
        onto = self.ds.graph(rdflib.URIRef(ONTOLOGY_GRAPH))
        onto.parse(source=str(CORE), format="turtle")
        onto.parse(data=EXTENSION, format="turtle")
        self.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(data=REPLICA, format="turtle")
        self.ds.graph(rdflib.URIRef(SERVICES_GRAPH)).parse(data=SERVICES, format="turtle")

    def sparql_api_query(self, query: str, out_format: str = "df") -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame([[None if v is None else str(v) for v in row] for row in res],
                            columns=[str(v) for v in res.vars])


@pytest.fixture(scope="module")
def client():
    return _Client()


def test_a_component_sees_the_configuration_that_applies_to_it(client):
    from backend.explorer import get_component_configuration
    recs = get_component_configuration(client, "Wind Park")
    got = {(r["instance"].rsplit("/", 1)[-1], r["service"], r["profile"], r["parameter"], r["value"])
           for r in recs}
    assert got == {
        ("Alkmaar", "WindForecast", "simulation_alkmaar", "ModelType", "Bastankhah_PorteAgel_2014"),
        ("Alkmaar", "WindForecast", "simulation_alkmaar", "WakeDecayConstant", "0.0324555"),
    }
    # the runtime profile applies to no component: it never lands on a park


def test_explorer_columns_name_the_service_and_stay_separate(client):
    from backend.explorer import attach_configuration, get_component_configuration
    df = pd.DataFrame({"URI": [f"{P}/WindPark/Alkmaar", f"{P}/WindPark/Other"],
                       "instance_id": ["Alkmaar", "Other"], "Roughness": ["1.0", ""]})
    out, cols, per = attach_configuration(df, get_component_configuration(client, "Wind Park"))
    assert set(cols) == {"ModelType (WindForecast)", "WakeDecayConstant (WindForecast)"}
    alk = out[out.instance_id == "Alkmaar"].iloc[0]
    assert alk["ModelType (WindForecast)"] == "Bastankhah_PorteAgel_2014"
    assert out[out.instance_id == "Other"].iloc[0]["WakeDecayConstant (WindForecast)"] == ""
    assert set(per) == {f"{P}/WindPark/Alkmaar"}


def test_the_service_view_lists_every_profile(client):
    from backend.explorer import get_service_configurations
    profiles = {p["profile"]: p for p in get_service_configurations(client)}
    assert set(profiles) == {"simulation_alkmaar", "runtime"}
    assert profiles["simulation_alkmaar"]["applies_to"] == [f"{P}/WindPark/Alkmaar"]
    assert profiles["runtime"]["applies_to"] == []
    assert profiles["runtime"]["parameters"] == [
        {"parameter": "OutputStream", "value": "windforecast.eolica.Alkmaar"}]
    assert {p["service"] for p in profiles.values()} == {"WindForecast"}


def test_component_table_endpoint_flags_the_config_columns(client, monkeypatch):
    """What the React explorer receives: config columns listed separately (the
    toggle hides them), values in the rows, per-instance detail for the panel."""
    pytest.importorskip("fastapi")
    import apps.api.explorer as api
    monkeypatch.setattr(api, "graph_client", lambda ctx: client)
    out = api.component_table("Wind Park", all_levels=False, ctx=None)
    assert out["has_config"] is True
    assert set(out["config_columns"]) == {"ModelType (WindForecast)",
                                          "WakeDecayConstant (WindForecast)"}
    assert set(out["config_columns"]) <= set(out["columns"])
    assert "Roughness" in out["columns"]                 # real attributes untouched
    alk = next(r for r in out["rows"] if r.get("instance_id") == "Alkmaar")
    assert alk["WakeDecayConstant (WindForecast)"] == "0.0324555"
    assert {r["parameter"] for r in out["configuration"]["Alkmaar"]} == {
        "ModelType", "WakeDecayConstant"}


def test_collections_offer_no_statistics_over_settings(client):
    """A configuration parameter attached to a component (an older build) is
    still not data about it: the Collections builder must not offer it."""
    from backend.collections.queries import workspace_attribute_types
    legacy = f"""
    @prefix dici_onto: <https://digicities.info/ontology#> .
    @prefix qudt: <http://qudt.org/schema/qudt/> .
    <{P}/WindPark/Alkmaar> dici_onto:hasAttribute <{P}/WindPark/Alkmaar/WakeDecayConstant> .
    <{P}/WindPark/Alkmaar/WakeDecayConstant> a dici_onto:WakeDecayConstant ; qudt:value 0.03 .
    """
    c = _Client()
    c.ds.graph(rdflib.URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).parse(data=legacy, format="turtle")
    types = {str(t).rsplit("#", 1)[-1] for t in workspace_attribute_types(c)["attrType"]}
    assert "Roughness" in types
    assert "WakeDecayConstant" not in types


def test_provisioning_loads_the_services_graph(tmp_path, monkeypatch):
    """services/*.ttl reach <services>, closed under the schema: the extension's
    ModelType ⊑ ConfigurationAttribute types the parameter node."""
    from backend.workspace import WorkspaceContext, graphdb_provisioning as gp
    from backend.workspace.storage import WorkspaceStorage

    (tmp_path / "ontology" / "extensions").mkdir(parents=True)
    (tmp_path / "ontology" / "extensions" / "ext.ttl").write_text(EXTENSION, encoding="utf-8")
    (tmp_path / "ingestion" / "output").mkdir(parents=True)
    (tmp_path / "ingestion" / "output" / "replica.ttl").write_text(REPLICA, encoding="utf-8")
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "WindForecast.ttl").write_text(SERVICES, encoding="utf-8")

    uploads: dict[str, str] = {}

    class _Backend:
        def dataset_exists(self, repo):
            return True

    monkeypatch.setattr(gp, "get_backend", lambda: _Backend())
    monkeypatch.setattr(gp, "_publish_local_working_copy", lambda ctx: None)
    monkeypatch.setattr(gp, "clear_default_graph", lambda repo: True)
    monkeypatch.setattr(gp, "upload_ttl_to_graph",
                        lambda repo, g, ttl, replace=True: uploads.__setitem__(g, ttl) or True)
    monkeypatch.setattr(gp, "_collections_fingerprint", lambda repo: None)
    monkeypatch.setattr(gp, "_stamp_collections_fingerprint", lambda repo, fp: None)
    monkeypatch.setattr(gp, "clear_graph", lambda repo, g: True)
    import backend.workspace.deletion as deletion
    monkeypatch.setattr(deletion, "touch_workspace_activity", lambda storage: None)

    ctx = WorkspaceContext(id="ws", name="ws", storage=WorkspaceStorage.local(str(tmp_path)),
                           graphdb_repository="ws")
    assert gp.ensure_workspace_repo(ctx)
    g = rdflib.Graph().parse(data=uploads[SERVICES_GRAPH], format="turtle")
    D = rdflib.Namespace("https://digicities.info/ontology#")
    param = rdflib.URIRef(f"{P}/services/WindForecast/config/simulation_alkmaar/ModelType")
    assert (param, rdflib.RDF.type, D.ConfigurationAttribute) in g
    # the inverse is materialized, and the schema itself stays in its own graph
    profile = rdflib.URIRef(f"{P}/services/WindForecast/config/simulation_alkmaar")
    assert (profile, D.configures, rdflib.URIRef(f"{P}/services/WindForecast")) in g
    assert (D.ModelType, rdflib.RDFS.subClassOf, D.ConfigurationAttribute) not in g
