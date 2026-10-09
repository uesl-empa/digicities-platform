# Connecting a new model or service to Digicities

This is the step-by-step recipe for wiring a new model or service (an energy
simulation, an optimizer, a forecaster, anything that takes building or system data and
returns a result) so a user can build a scenario in Digicities and submit it.

It is written from the worked example of a flexibility optimizer service. Follow
the same steps for any new service. The order matters: model the data first, then the
payload, then the transport.

The guiding rule: **Digicities stays generic. Everything specific to one model lives in
its requirements template and, if needed, a small adapter on the service side.** Do not
put model-specific logic into the Digicities platform.

## What you need before you start

Answer three questions about the service:

1. **What input does it expect?** The exact fields, their units, and their types. For
   the optimizer: `floor_area` (m2), `PH_power` (kW), `heat_capacity`, `tariff_type`
   (one of flat/variable/dual), `months`, and so on.
2. **How do you talk to it?** HTTP request/response, a Redis stream, something else.
3. **What does it return?** So you know what a successful result looks like.

Write these down. They drive everything below.

## Step 1 - Model the inputs in the ontology

Every input the service needs should be a described concept, not a bare number.

- For each input, find an existing attribute class in the core ontology and reuse it
  (the optimizer's floor area reused core `GroundFloorArea`). If it does not exist,
  add it in your workspace's `ontology/extensions/<name>.ttl`.
- A new attribute is a class that is a subclass of two things: its kind
  (`PhysicalAttribute` for a measured quantity, `CategoricalAttribute` for a choice,
  and so on) and the component attribute group (`BuildingAttribute`, `LocationAttribute`,
  etc.). Give it an `rdfs:label`.
- For a categorical attribute, also declare its allowed values as classes (we declared
  `Flat`, `Variable`, `Dual` under `ElectricityTariff`).
- **Make sure the component type exists and is a `Component`.** This bit catches people
  out: `Building` was not in the core ontology, so until we added
  `dici_onto:Building rdfs:subClassOf dici_onto:Component` the building did not appear in
  the Explorer or Scenario Builder at all.
- Where possible, pin units with QUDT (`hasDefaultUnit`, `hasQuantityKind`).

Example (from a workspace's `ontology/extensions/*.ttl`):

```turtle
dici_onto:Building a owl:Class ;
    rdfs:subClassOf dici_onto:Component ; rdfs:label "Building" .

dici_onto:PeakSpaceHeatingPower a owl:Class ;
    rdfs:subClassOf dici_onto:PhysicalAttribute, dici_onto:BuildingAttribute ;
    rdfs:label "Peak Space Heating Power" .

dici_onto:ElectricityTariff a owl:Class ;
    rdfs:subClassOf dici_onto:CategoricalAttribute, dici_onto:BuildingAttribute .
dici_onto:Flat a owl:Class ; rdfs:subClassOf dici_onto:ElectricityTariff .
```

## Step 2 - Provide sample data

Add instances in `ingestion/output/<name>.ttl` so the component shows up in the Digital
Replica Explorer and can be picked in the Scenario Builder. A building instance links
each attribute two ways and carries the value in `qudt:value`:

```turtle
<.../Building/100001> a dici_onto:Building ;
    rdfs:label "Demo Flexible Building" ;
    dici_onto:hasAttribute <.../Building/100001/PeakSpaceHeatingPower> ;
    dici_onto:hasBuildingPeakSpaceHeatingPowerAttribute <.../Building/100001/PeakSpaceHeatingPower> .
<.../Building/100001/PeakSpaceHeatingPower> a dici_onto:PeakSpaceHeatingPower, dici_onto:PhysicalAttribute ;
    qudt:value "10.0"^^xsd:decimal ; qudt:unit unit:KiloW .
```

**Put the value in `qudt:value`.** The converter reads `qudt:value`. It does not read
`hasAttributeValue`, so a value placed only there will silently not come through.

## Step 3 - Write the service requirements template

This is the heart of the integration. Create `services/<service>.yaml`. It describes the
payload the service wants, with each field pointing at an ontology attribute. The left
side is the field name the service (or its adapter) reads; the right side is the ontology
reference Digicities resolves from the scenario.

```yaml
service_name: FlexibilityOptimizer
description: Single-building flexibility optimization.
scenario_data:
  uri: Scenario.URI
  location:
    link: CL.Scenario.Location
    template:
      uri: Location.URI
      weather_location: Location.WeatherEPW
      buildings:
        link: CL.Location.Building
        template:
          uri: Building.URI
          GrossFloorArea: Building.GroundFloorArea
          PeakSpaceHeatingPower: Building.PeakSpaceHeatingPower
          ElectricityTariff: Building.ElectricityTariff
          Months: Building.OptimizationMonths
```

`CL.Scenario.Location` means "the Locations linked to the Scenario"; `CL.Location.Building`
means "the Buildings linked to each Location". `Building.GroundFloorArea` resolves that
building's GroundFloorArea value.

### Inputs that are statistics over linked components

Some models want a statistic rather than the raw records: the mean and standard deviation
of the apple weights on each tree, the total floor area of the buildings in a district. No
file states these, so do not add them as columns. Record the individual components (each
apple, linked to its tree) and request the statistic as `<Container>.<Attribute><Statistic>`,
where the statistic is one of `Mean`, `Median`, `Sum`, `MinValue`, `MaxValue`, `Count`,
`StandardDeviation`. List each one under `derived_attributes`:

```yaml
scenario_data:
  tree:
    uri: Tree.URI
    WeightMean: Tree.WeightMean                              # mean of Apple.Weight per Tree
    WeightStandardDeviation: Tree.WeightStandardDeviation
    WeightCount: Tree.WeightCount                            # how many apples
derived_attributes:
  - Tree.WeightMean
  - Tree.WeightStandardDeviation
  - Tree.WeightCount
```

At convert time the platform computes them from the components linked to each tree
(the Collections module, `ensure_template_aggregates`) and the converter reads them like
any attribute. `derived_attributes` tells the Scenario Builder not to require them on the
stored instances, since they only exist once computed. A Count carries no unit; a
statistic of a group with too few members (a standard deviation of one value) is left out.

### Settings the model needs: configuration, not data

A value that sets a **boundary condition of the model run** (a model or algorithm choice,
a calibration constant, a run name or frequency) is configuration, not a
property of a component. A live data stream that delivers a component's values is not configuration: it belongs to that component, as the `hasLiveTimeSeriesReference` of one of its attributes. Do not model a config file as a component, and do not put such a
value on a component as an attribute. Record it as a `ConfigurationAttribute` in a
`ServiceConfiguration` profile of the service, in `services/<service>.ttl` next to the
requirements; `appliesTo` names the components a profile is tuned for:

```turtle
<.../services/WindForecast> a dici_onto:Service ;
    dici_onto:hasConfiguration <.../services/WindForecast/config/simulation_alkmaar> .
<.../services/WindForecast/config/simulation_alkmaar> a dici_onto:ServiceConfiguration ;
    dici_onto:appliesTo <.../WindPark/Alkmaar> ;
    dici_onto:hasConfigurationParameter <.../config/simulation_alkmaar/WakeDecayConstant> .
<.../config/simulation_alkmaar/WakeDecayConstant>
    a dici_onto:WakeDecayConstant, dici_onto:ConfigurationAttribute ;
    dici_onto:hasAttributeValue "0.0324555" .
```

The parameter class (`WakeDecayConstant`) goes in your extension under its value kind and
`ConfigurationAttribute`. The file is loaded into the workspace's `<http://services>` graph;
the React Explorer shows a component's configuration behind its **Show config parameters**
toggle, and API Submission lists every profile per service. The onboarding agent writes
these profiles for you. Configuration does not go into the payload today.

## Step 4 - Provide a demo scenario

Add a self-contained scenario in `scenarios/<name>.ttl`. The converter reads only this
one file, so it must contain everything: the `Scenario`, the components, their
attributes, and the links. Links are not plain triples, they are `ComponentLink` nodes:

```turtle
<.../FlexibilityDemo> a dici_onto:Scenario ; rdfs:label "Flexibility Demo" .
<.../ComponentLink_1> a dici_onto:ComponentLink ;
    dici_onto:hasInputEntity <.../FlexibilityDemo> ;
    dici_onto:linksInputyEntityTo <.../Location/EmpaCampus> .
<.../ComponentLink_2> a dici_onto:ComponentLink ;
    dici_onto:hasInputEntity <.../Location/EmpaCampus> ;
    dici_onto:linksInputyEntityTo <.../Building/100001> .
```

Note the property name `linksInputyEntityTo` (yes, the spelling is odd; match it exactly).
In normal use the Scenario Builder generates this file for you. You only hand-write one
to ship a ready-made demo.

## Step 5 - Build the transport (service side)

Two cases:

- **The service already speaks HTTP and accepts the Digicities payload.** Nothing to
  build. Register it directly (Step 6).
- **The service uses a stream, or wants different field names/shape (the common case).**
  Write a small adapter that accepts the Digicities payload, maps it to the service's
  exact parameters, delivers it, and returns the result. Keep all the model-specific
  mapping here, not in Digicities.

For the optimizer (a Redis-stream consumer) we added a tiny FastAPI adapter,
`flexibility-adapter`, that accepts the scenario payload, maps building attributes to the
optimizer's fields, publishes to the request stream, waits for the result, and returns
it. It is about 200 lines and wired into the stack's docker-compose on a local port.

## Step 6 - Register the service in Digicities

In the app, go to **API Submission -> Config**, pick the service, and set:

- **Transport `http`**: the endpoint URL. If both run on your machine in containers, use
  `http://host.docker.internal:<port>/...`, not `localhost` (the app runs inside a
  container, so `localhost` would mean the app itself).
- **Transport `redis`**: the host, port, request stream, result stream, and payload
  field. Use `host.docker.internal` for the host when Redis runs in another stack.

## Step 7 - Run it end to end

**API Submission -> Upload & Convert**: pick the scenario and the service template, click
Convert. **API Submission -> Submission**: pick the service and the converted scenario,
click Submit. You should get the model's result back.

## Conventions checklist (the things that bite)

- The component type must be `rdfs:subClassOf* dici_onto:Component`, or it will not show
  in the Explorer or Scenario Builder.
- Attribute values the converter reads must be in `qudt:value`.
- A categorical value is the IRI the attribute node points at with `dici_onto:hasCategoricalValue`
  (a named individual of the attribute's class). Data written before that property was stated
  typed the node with the category instead; the converter still reads that until the workspace
  is rebuilt.
- Scenario links are `dici_onto:ComponentLink` nodes with `dici_onto:hasInputEntity` and
  `dici_onto:linksInputyEntityTo`.
- Keep model-specific mapping in the adapter or the template. Digicities stays generic.
- A statistic over linked components is requested as `<Container>.<Attribute><Statistic>`
  and listed under `derived_attributes`, never stored as a column.
- A model setting (a boundary condition of the run) is configuration in the service TTL,
  never a component or a component attribute.
- Endpoint URLs from the running app use `host.docker.internal`, not `localhost`.
- After changing an extension, re-open the workspace so its database re-provisions.

## Where things live (summary)

| Piece | Lives in | Purpose |
|-------|----------|---------|
| Attribute and component classes | `ontology/extensions/*.ttl` | Describe what the data means |
| Sample instances | `ingestion/output/*.ttl` | Show the component in the UI |
| Service requirements template | `services/*.yaml` | Map ontology -> the service payload |
| Service requirements + configuration profiles | `services/*.ttl` | What the service needs and how it runs (loaded into `<http://services>`) |
| Demo scenario | `scenarios/*.ttl` | A ready-to-submit example |
| Transport adapter (if needed) | the service's own repo | Map and deliver to the model |
| Endpoint registration | API Submission -> Config (in-app) | Where to send it |
