# Onboarding a usecase: from a messy data dump to a submitted scenario

You have an **existing model** (a simulator, optimizer, forecaster, …) and a
**pile of input data** in whatever ad-hoc format its author left it. This guide
takes you from there to a working Digicities **workspace** you can build a
scenario in and **submit** to the model.

It's the front-to-back path. For the service-wiring detail it leans on
[`INTEGRATING_A_SERVICE.md`](INTEGRATING_A_SERVICE.md); for the folder contract on
[`WORKSPACE_LAYOUT.md`](WORKSPACE_LAYOUT.md); for the ontology on
[`SEMANTIC_LAYER.md`](SEMANTIC_LAYER.md). Read this once end-to-end, then work
each step.

> **Onboarding kit.** A model-agnostic brief for driving this with an agent lives
> in [`onboarding-kit/`](../onboarding-kit/): drop its `AGENTS.md` into any working
> folder (a model + its data), point an agent at that folder and this running
> ecosystem, and it works the steps below. The bundled `demo_workspaces/`
> energy-simulation example is a worked reference to compare against.

## A note on judgement — confirm, don't guess

The modelling here is yours to decide, but the **consequential** decisions should
be **confirmed with the model author**, not guessed: which core class a new
component or attribute hangs off (its parent), creating a new hierarchy branch
under core, whether an attribute is physical vs categorical vs dynamic, a
categorical's allowed values, a unit, or how entities link. Propose your
reasoning, get sign-off, then commit. Silent guesses on these change what the data
*means*.

## The mental model

Digicities represents a system as **components** (Buildings, Roads, Rooms, …),
each carrying **attributes** (values described by the ontology), wired together by
**links**. A **scenario** is a snapshot of that graph. A **service template**
says how to turn a scenario into the exact payload your model wants. Digicities
itself stays generic — everything model-specific lives in the template and, if
needed, a small adapter on the service side.

So onboarding is mostly **describing your data in the ontology**, then **mapping
it to your model's payload**.

## Step 0 — Understand the data and the model

Before touching Digicities, answer (from the model's code + its data files):

1. **What are the entities, and how do they nest?** e.g. *city → road segments*,
   or *building → rooms*. This becomes your component hierarchy + links.
2. **What attributes does each entity have, with units?** Read the model to see
   what it actually consumes — the input files' column names are often wrong or
   ambiguous; the code is the ground truth.
3. **What payload does the model expect, and how do you talk to it?** HTTP JSON,
   a Redis stream, a CLI? What does a successful result look like?

Write these down. They drive every step.

## Step 1 — Create the workspace

A workspace is a folder with the structure in
[`WORKSPACE_LAYOUT.md`](WORKSPACE_LAYOUT.md). Two ways:

- **In-app:** landing page → *Create a new workspace* (creates the folders +
  `workspace_meta/metadata.json` for you).
- **By hand:** create the folder tree and a `workspace_meta/metadata.json`
  (`id`, `name`, `description`, `tags`). Copy the shape of
  `demo_workspaces/energy-simulation/`.

The platform treats any folder with a populated `ontology/extensions/`,
`ingestion/output/`, or `scenarios/` as a workspace.

**Making it visible to the running app:** the app reads workspaces from whatever
is mounted at `/app/data/usecases`. By default `docker-compose.override.yml`
mounts `./demo_workspaces`. Either drop your workspace folder into
`demo_workspaces/`, or set `USECASES_HOST_PATH=<folder-holding-your-workspaces>`
in `.env` and restart Streamlit (`docker compose up -d`).

## Step 2 — Model the data in the ontology (your design decision)

This is the part you decide, not a lookup.

**First, inspect what the core ontology already covers, and reuse it.** Don't
invent a concept that exists. Browse the existing component and attribute classes
with the **Ontology Manager** and **Digital Replica Explorer** modules (or query
the graph — see [`SEMANTIC_LAYER.md`](SEMANTIC_LAYER.md)). The core already
defines, among others: `Component`, `Location`, `LocationAttribute`, `Attribute`,
`PhysicalAttribute`, `CategoricalAttribute`, `StaticAttribute`, `DynamicAttribute`.

**Map by meaning, not by name.** Every core term is annotated with a description
(`rdfs:comment`), a precise definition (`skos:definition`), synonyms
(`skos:altLabel` — e.g. `Location` lists "Site", "Area", "Zone"), examples
(`skos:example` — "a wind park, a city district, a campus"), and disambiguation
notes (`skos:scopeNote`). Use them: the ontology repo ships a generated lookup at
`docs/term-index.json` / `docs/term-index.md` and a decision procedure in
`docs/AGENT_MAPPING_GUIDE.md`. A concept whose name matches nothing in core
(a *WindPark*) usually still has an exact home (`Location`) — the synonyms and
examples are how you find it.

**Then decide the vocabulary this usecase needs** for whatever the core doesn't
cover: the new component types, which attributes each carries, whether each is
physical / categorical / dynamic / cost / …, the allowed values for categoricals,
and how components link. Author it with the **Ontology Manager** (it writes
`ontology/extensions/<name>.ttl`). This is
[`INTEGRATING_A_SERVICE.md`](INTEGRATING_A_SERVICE.md) step 1.

You need to know *how* the platform represents these things — the rules below.
*What* to represent is yours to work out from the data + the model.

**The representation pattern** (names are illustrative — choose your own):
`demo_workspaces/energy-simulation/ontology/extensions/energy_sim_extension.ttl`
is a complete worked example to learn the shape from.

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

# 1. the component type — MUST be under Component or it won't appear in the UI.
#    Annotate it: the comment/synonyms/examples are how the next agent (or
#    partner) maps onto YOUR term instead of minting a duplicate.
dici_onto:RoadSegment a owl:Class ;
    rdfs:subClassOf dici_onto:Component ; rdfs:label "Road Segment" ;
    rdfs:comment "A stretch of road between two junctions, carrying traffic flow"@en ;
    skos:altLabel "Road Link"@en ; skos:example "A 400 m arterial segment between two intersections"@en .

# 2. an attribute-group class for that component, under Attribute.
#    THIS IS THE STEP PEOPLE MISS: the group class must be defined before you use it.
dici_onto:RoadSegmentAttribute a owl:Class ;
    rdfs:subClassOf dici_onto:Attribute ; rdfs:label "Road Segment Attribute" ;
    rdfs:comment "Typing marker grouping attributes that apply to a Road Segment"@en .

# 3. each attribute — subclass of its KIND (Physical / Categorical / …) AND the group
dici_onto:SegmentCapacity a owl:Class ;
    rdfs:subClassOf dici_onto:PhysicalAttribute, dici_onto:RoadSegmentAttribute ;
    rdfs:label "Segment Capacity" ;
    rdfs:comment "Maximum vehicle throughput of the segment, in vehicles per hour"@en .

# 4. a categorical attribute also declares its allowed values as subclasses
dici_onto:InsulationClass a owl:Class ;
    rdfs:subClassOf dici_onto:CategoricalAttribute, dici_onto:RoomAttribute ;
    rdfs:label "Insulation Class" ;
    rdfs:comment "Thermal insulation quality category of a room"@en .
dici_onto:Poor a owl:Class ; rdfs:subClassOf dici_onto:InsulationClass ; rdfs:label "Poor" ;
    rdfs:comment "Poor insulation: significant heat loss"@en .
```

(Reuse `dici_onto:Location` from core as the top-level container — that's how the
energy-simulation example links `Scenario → Location → Building`.)

After editing an extension, **re-open the workspace** so its dataset
re-provisions with the new classes.

## Step 3 — Build the digital replica (the instances)

Put instances in `ingestion/output/<name>.ttl`: your actual components with their
attribute values in `qudt:value`. The fast path is the **Replica Builder** module's
Excel Import — fill the 6/7-row-header template and convert. The blank template ships at
`tutorial/sample_data/alpine_village_replica_template.xlsx` (and a per-attribute
CSV reference at `data/ingestion_template/`). Walk
[`tutorial/09_excel_import.ipynb`](../tutorial/09_excel_import.ipynb): each sheet
is a component class, each row an instance, each column an attribute.

The importer maps your messy source columns → typed ontology attributes. This is
where the ad-hoc CSV/JSON becomes queryable, described data.

## Step 4 — Write the service requirements template

`services/<service>.yaml` maps the ontology to your model's payload. This is the
heart of the integration — [`INTEGRATING_A_SERVICE.md`](INTEGRATING_A_SERVICE.md)
step 3, and the two bundled templates in `data/global_services/` are the exact
shape to copy. The left side is the field name your model reads; the right side
is the ontology reference Digicities resolves from the scenario:

```yaml
service_name: TrafficForecaster
description: Next-hour flow + congestion per road segment.
# `connection:` lets Digicities auto-register the endpoint on workspace open.
connection:
  transport: http
  url: ${TRAFFIC_SERVICE_URL:-http://host.docker.internal:8010/api/digicities/run}
  method: POST
scenario_data:
  uri: Scenario.URI
  city:
    link: CL.Scenario.Location
    template:
      uri: Location.URI
      segments:
        link: CL.Location.RoadSegment
        template:
          uri: RoadSegment.URI
          capacity_vph: RoadSegment.SegmentCapacity
          freeflow_kph: RoadSegment.FreeFlowSpeed
```

You can build this visually in **Service Requirements Builder** (load an existing
template to see the shape), or hand-write it.

## Step 5 — Create scenarios

In the **Scenario Builder**, pick components from your replica and derive a
scenario (baseline, or with assumptions applied). It writes `scenarios/<name>.ttl`
for you — a self-contained `Scenario` + components + attributes + `ComponentLink`
nodes. To ship a ready-made demo you can hand-write one
([`INTEGRATING_A_SERVICE.md`](INTEGRATING_A_SERVICE.md) step 4).

## Step 6 — Wire the transport and register

- **Model already speaks HTTP and accepts the payload?** Register it directly.
- **Model uses a stream, or wants a different shape (common)?** Write a small
  adapter (HTTP in → model's native call → result out). Keep all model-specific
  mapping there, not in Digicities.
  ([`INTEGRATING_A_SERVICE.md`](INTEGRATING_A_SERVICE.md) step 5.)

Register the endpoint in **API Submission → Config** (or via the template's
`connection:` block). Use `host.docker.internal:<port>` for local containers.

## Step 7 — Run it end to end

**API Submission → Upload & Convert**: pick the scenario + service template,
Convert (check every field resolved — no `.URI`/`.label` leftovers). **→
Submission**: pick the service + converted scenario, Submit. You should get the
model's result back.

## Done when

- The workspace opens and its components show in the Explorer.
- A scenario converts against the template with all attributes resolved.
- Submit returns the model's result.

## Checklist of the things that bite

- Component types under `dici_onto:Component`; attribute values in `qudt:value`.
- Query the graph semantically (`subClassOf*`), never by class-name string match.
- Re-open the workspace after ontology edits.
- `host.docker.internal`, not `localhost`, from the running app.
- Keep model-specific logic in the template/adapter; Digicities stays generic.
