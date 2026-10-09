# Why not X? How Digicities relates to other standards

Status: written 2026-10-09. Standards move; if something here is out of date, please open an issue.

Digicities is a requirements-driven semantic layer that connects models to the data they need. Each
model states its inputs as requirements against a shared ontology. The platform then finds, checks
and delivers that data from a knowledge graph.

People who know the field often ask why we did not simply use one of the standards below. The short
answer: most of them describe data well, and several are better than Digicities at that. None of them
starts from what a model needs and turns that into a checked input for the model. That is the gap
Digicities fills, and it is designed to work with these standards, not to replace them.

This page is honest about both sides. What Digicities cannot do yet is listed in
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) and [SEMANTIC_LAYER.md](SEMANTIC_LAYER.md).

## What Digicities does, in one paragraph

A model (we call it a service) publishes a contract: the components, attributes and links it needs,
written as paths such as `WindTurbine.HubHeight` or `CL.WindPark.WindTurbine`. Data owners onboard
their data into a workspace as a replica: instances of ontology classes with their attributes and
links, stored in a knowledge graph. A scenario picks instances from the replica and changes some
values. Before anything is sent, the platform checks that the scenario carries every attribute and
link the contract requires. It then builds the payload in the shape the model asked for and sends it
over HTTP or Redis. The contract, not the data source, decides what is assembled.

## FIWARE Smart Data Models and NGSI-LD

**What it is.** NGSI-LD is an ETSI standard API for managing context information: applications
create, update and query entities and subscribe to changes. Its data model builds on property graphs
and is exchanged as JSON-LD ([ETSI GS CIM 009](https://cim.etsi.org/NGSI-LD/official/front-page.html);
[ETSI press release](https://www.etsi.org/newsroom/press-releases/1519-2019-01-etsi-cim-group-releases-full-feature-specification-for-context-information-exchange-in-smart-cities)).
Smart Data Models is a joint programme led by the FIWARE Foundation, IUDX, TM Forum and OASC that
curates open data models for many domains, including energy
([Smart Data Models on GitHub](https://github.com/smart-data-models);
[smartdatamodels.org](https://smartdatamodels.org/)). Context brokers such as Scorpio implement the
API ([Scorpio](https://hub.docker.com/r/fiware/scorpio)).

**What it does well.** A mature, standard API for live context data, with subscriptions and history.
A large catalogue of ready-made entity models with JSON Schema validation and NGSI-LD examples.
Strong uptake in smart-city platforms.

**Overlap.** Both describe entities, their properties and their relationships as a graph, and both
use linked-data identifiers.

**The difference.** NGSI-LD standardises how data is stored, queried and pushed. It does not let a
model declare which data it needs, and it does not check a set of entities against those needs before
a run. Digicities adds that contract and the check. In turn, Digicities has no standard query and
subscription API for outside clients, and its catalogue of domain models is much smaller.

**How to combine them.** NGSI-LD could be another transport: Digicities builds the checked input,
and a broker delivers it or holds the live streams a model reads. A Smart Data Model entity type can
be linked to the matching Digicities class so its data can be onboarded into a replica. Neither is
built today.

## IDS Information Model (International Data Spaces)

**What it is.** An RDFS/OWL ontology for data spaces. It describes the actors in a data space, how
they interact, the resources they exchange, and the rules for using data
([Fraunhofer publication](https://publica.fraunhofer.de/handle/publica/409235)). It is deliberately
general and relies on other vocabularies for domain facts. Its usage contracts are expressed with the
IDS Usage Contract Language ([Fraunhofer](https://publica.fraunhofer.de/entities/publication/5f612117-0677-403b-81b4-f5ef5fd53a70)).
The GitHub repository was at release 4.1.0 and was archived (read-only) in June 2025
([InformationModel on GitHub](https://github.com/International-Data-Spaces-Association/InformationModel)).

**What it does well.** Data sovereignty: who may use which data, under which contract, through which
connector. That is a problem Digicities does not address.

**Overlap.** Both describe resources and services with an ontology, and both talk about contracts.

**The difference.** An IDS contract governs use: who may access the data and on what terms. A
Digicities contract governs content: which components, attributes and links a model needs to run.
IDS says nothing about whether a payload is complete for a model. Digicities has accounts and
workspace access control, but no usage policies, no connectors and no data-space membership.

**How to combine them.** They work at different layers. A Digicities service could be offered through
an IDS connector, with the IDS contract covering use and the Digicities contract covering content.
This is not built today.

## Brick

**What it is.** An open-source (BSD-3-Clause) metadata schema for buildings. It is an RDF class
hierarchy for building subsystems, equipment and points, plus a small set of relationships that link
them into a graph ([Brick on GitHub](https://github.com/BrickSchema/Brick);
[brickschema.org](https://brickschema.org/); [original paper](https://par.nsf.gov//servlets/purl/10074644)).
Its Python tooling validates models with SHACL shapes
([brickschema validation docs](https://brickschema.readthedocs.io/en/latest/validate.html)).

**What it does well.** Detailed, community-maintained vocabulary for HVAC, lighting, metering and the
points that sensors and controllers expose. It lets building analytics run across buildings without
site-specific labels.

**Overlap.** Both are RDF ontologies. Both describe equipment, locations and the links between them.

**The difference.** Brick goes deep in one domain. Digicities keeps a shallow core (components with
attributes and links) and expects detailed domains to come from schemas like Brick. Brick describes a
building; it does not state what a model needs or assemble a model input. Digicities has nothing close
to Brick's depth for buildings.

**How to combine them.** Link Digicities classes to Brick classes with SKOS mapping properties
(`skos:closeMatch`, `skos:exactMatch`), so Brick-described data can be found and used in a replica.
The Ontology Manager can already record such links. A first set of Brick alignments exists as a
workspace extension, and a maintained alignment module is planned; it is not part of the published
core yet.

## SHACL alone

**What it is.** The W3C Recommendation (July 2017) for validating RDF graphs. Conditions are written
as shapes in a shapes graph and checked against a data graph; the result is a validation report
([W3C SHACL](https://www.w3.org/TR/shacl/)). It covers cardinality, datatypes, value ranges and much
more.

**What it does well.** Rigorous, standard, tool-supported validation of graph data. Brick and the IDS
Information Model both use it.

**Overlap.** A Digicities service contract is a statement of what a valid input looks like. That is
exactly what a SHACL shape is.

**The difference.** SHACL checks a graph you already have. It does not say where the data comes from,
how to pick instances from a replica into a scenario, or how to turn the graph into the JSON a model
expects. Digicities does those steps. Its contract language is simpler than SHACL today: it checks
that required attributes and links are present and resolve. It cannot yet state value ranges or
allowed units the way a SHACL shape can.

**How to combine them.** SHACL is the planned formal version of the contract. Each service contract
would compile to shapes, and scenarios would be validated against them before submission (see
[SEMANTIC_LAYER.md](SEMANTIC_LAYER.md)). This is planned, not built.

## OEO (Open Energy Ontology)

**What it is.** A domain ontology for energy system analysis, built on the Basic Formal Ontology (BFO)
and developed by the Open Energy Family. It is published under CC0 or MIT and hosted on the Open
Energy Platform ([OEO on GitHub](https://github.com/OpenEnergyPlatform/ontology)). It is used to
annotate datasets and model descriptions so they can be found, compared and coupled
([Booshehri et al. 2021, Energy and AI](https://doi.org/10.1016/j.egyai.2021.100074);
[open access](https://doaj.org/article/73065595b4324173a98f2b649e5aabf1)).

**What it does well.** A carefully defined, community-reviewed vocabulary for energy systems analysis,
with frequent releases and a strong link to scenario and model metadata on the Open Energy Platform.

**Overlap.** Both serve energy researchers, and both aim to make data and models interoperable.

**The difference.** OEO defines what terms mean; it is the more rigorous vocabulary of the two.
Digicities is a working layer: a replica of real instances, scenarios, and contracts that assemble
model inputs. OEO follows BFO's split between things and processes, which Digicities' core does not
use, so a one-to-one equivalence would import commitments that do not hold.

**How to combine them.** Annotate Digicities classes with SKOS links to OEO terms (`skos:closeMatch`,
`skos:relatedMatch` where the categories differ) rather than `owl:equivalentClass`. A first set of
about 25 OEO alignments exists as a workspace extension; it is not yet in the published core.

## CESDM (Common Energy System Domain Model)

**What it is.** A schema-driven, tool-independent framework for energy-system modelling, released as
an MIT-licensed Python toolbox. Entities, attributes and relations are defined in YAML schemas, models
are checked against analysis validation profiles (for example power flow, optimal dispatch), and data
moves as YAML, Frictionless packages, HDF5 or CSV/Excel
([cesdm-toolbox on GitHub](https://github.com/cesdm/cesdm-toolbox)). It is not the same project as
the LinkML-based Common Energy System Model (CESM) of G-PST.

**What it does well.** Concrete adapters to established power-system tools: import and export for
pandapower and MATPOWER, import from PyPSA and TYNDP data. That is real, immediate interoperability
with those tools, which Digicities does not have.

**Overlap.** The closest match in philosophy. CESDM's entity-attribute-relation pattern is the same
idea as Digicities' component-attribute-link pattern, and its analysis profiles play a similar role to
a Digicities service contract: what a given analysis needs.

**The difference.** CESDM works on files and Python objects passed between tools. Digicities keeps
the data in a live knowledge graph with formal class hierarchies, multi-user workspaces, scenarios, and
an agent that onboards a folder without code. CESDM has no knowledge graph; Digicities has no ready
adapters to PyPSA, pandapower or MATPOWER.

**How to combine them.** An importer that reads CESDM YAML into a Digicities replica, and an exporter
that writes a workspace out as CESDM YAML. The exporter would connect Digicities to the power-system
tools CESDM already supports. Neither exists yet.

## Summary

| Standard | What it standardises | What Digicities adds | What Digicities lacks | How to combine |
|---|---|---|---|---|
| NGSI-LD and Smart Data Models | An API for live context data; a catalogue of entity models | A contract per model and a completeness check before a run | A standard query and subscription API; a large model catalogue | Broker as a transport or stream source; link entity types to classes (not built) |
| IDS Information Model | Data-space actors, resources and usage contracts | Contracts about content (what a model needs) | Usage policies, connectors, data sovereignty | Offer services through an IDS connector (not built) |
| Brick | Building equipment, points and their relationships | Model contracts and input assembly across domains | Brick's depth for buildings | SKOS links to Brick classes (prototype alignment exists) |
| SHACL | Validation of RDF graphs against shapes | Finding data, building scenarios, producing model payloads | Range, unit and datatype checks in contracts | Compile contracts to SHACL shapes (planned) |
| OEO | A rigorous energy-system-analysis vocabulary | A working replica, scenarios and contracts | OEO's rigour and BFO grounding | SKOS links to OEO terms (prototype alignment exists) |
| CESDM | A YAML entity-attribute-relation schema and tool adapters | A live knowledge graph, workspaces, onboarding agent | Adapters to PyPSA, pandapower, MATPOWER | CESDM importer and exporter (not built) |
