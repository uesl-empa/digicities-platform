"""A flow's ends in a service contract are links, never required attributes.

``EnergyCarrierFlow.hasSource`` / ``.hasDestination`` give a service the URIs of
the components a flow leaves and enters (test_template_flow_ends.py). Read as
attributes, the scenario's completeness gate demanded an attribute "hasSource"
that no flow holds, and the contract could not be met.
"""
from backend.scenario_builder.requirements import extract_required_attributes_enhanced
from backend.service_requirements.contract import parse_reference, required_references

CONTRACT = {"scenario_data": {"flows": {"link": "CL.Junction.EnergyCarrierFlow", "template": {
    "uri": "EnergyCarrierFlow.URI", "source": "EnergyCarrierFlow.hasSource",
    "destination": "EnergyCarrierFlow.hasDestination", "efficiency": "EnergyCarrierFlow.FlowOutEff"}}}}


def test_a_flow_end_is_no_attribute():
    ref = parse_reference("EnergyCarrierFlow.hasSource")
    assert ref.flow_end == "hassource" and ref.attribute is None and ref.attribute_ref is None
    assert parse_reference("EnergyCarrierFlow.FlowOutEff").flow_end is None


def test_the_completeness_gate_does_not_ask_for_a_flow_end():
    texts = {r.text for r in required_references(CONTRACT)}
    assert texts == {"EnergyCarrierFlow.URI", "EnergyCarrierFlow.FlowOutEff"}
    required, _nested = extract_required_attributes_enhanced(CONTRACT)
    assert "hasSource" not in required["EnergyCarrierFlow"]
    assert "hasDestination" not in required["EnergyCarrierFlow"]
