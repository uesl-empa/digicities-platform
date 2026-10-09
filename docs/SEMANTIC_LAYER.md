# Strengthening Digicities as a semantic layer

Digicities is a requirements-driven semantic layer that connects models to the data they
need: each model states its inputs as requirements against a shared ontology, and the
platform finds, checks and delivers that data from a knowledge graph.

This document says what that takes, what is in place and what is still missing. It is
ordered by value, not by effort. For the dated list of everything that does not work
yet, see [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md); this page no longer keeps its
own list.

Current state (2026-10-09): scenarios are checked against the service's contract before
they are sent (see P0 below). Two gaps remain
that matter most. The checks look at completeness, not at units, types or allowed
values. And a service-side adapter (the flexibility optimiser's, for example) can still
match names loosely and fill in defaults, which hides missing data from the user.

## P0 - Enforce the contract (validation before submission)

Status: in place for completeness, not yet for units, types or allowed values.

`validate_payload` (`backend/api_submission/validation.py`) checks every converted
payload against the service's contract before it is sent:

- a template reference that did not resolve to a value is reported (an error when the
  field is listed under `required_attributes`, a warning otherwise),
- a value that still holds the unresolved reference (for example the text
  `Building.PeakSpaceHeatingPower` instead of a number) is reported the same way,
- a component link that produced no components is an error.

Where it runs: the REST convert (`POST .../submission/convert`) returns the report with the
payload; the Streamlit Submit tab skips every scenario that fails and says which; the
onboarding agent's payload check holds the contract to the same rules. The REST submit
(`POST .../submission/submit`) does not re-check the report: it only refuses an empty payload
(unless the caller passes `force=true`). See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

Still to do: check values against the expected unit, type and allowed set. That is the
job of the SHACL shapes described below. The goal stays the same: a green tick should
mean "this building genuinely has what the model needs", not "we sent something and the
service filled the blanks".

Why it matters: this is what turns a nice vocabulary into a dependable contract. It is
also what makes results trustworthy, because you know the inputs were complete.

## P0 - Make the mapping declarative, shrink the adapter

Today the service-side adapter holds the knowledge of "Digicities `GrossFloorArea`
means the optimizer's `floor_area`", plus alias matching and defaults. That is
pragmatic glue, but it means meaning leaks into per-service Python.

Direction: the service requirements template should carry the full mapping (ontology
attribute -> the field name and unit the service expects), so Digicities emits exactly
what the service wants. The adapter then becomes a thin transport shim with no business
logic. The alias-matching in the adapter is a signal that the ontology-to-service
contract is not tight yet.

Why it matters: every bit of mapping logic that lives in a bespoke adapter is a bit of
the "semantic layer" that is actually hidden in code. Pull it back into the declarative
template and the ontology.

## P1 - Pin units, quantity kinds, and categorical vocabularies

The optimizer wanted kW and square metres; tariffs had to be one of flat, variable,
dual. Right now those expectations live in the model, not the ontology.

- Use QUDT consistently (`hasDefaultUnit`, `hasQuantityKind`) on attribute classes so a
  value carries its unit and can be checked or converted.
- Define categorical attributes with their allowed value set as named individuals or
  classes (we did this for `ElectricityTariff` -> Flat/Variable/Dual). Make that the
  norm, not the exception.

Why it matters: units and value sets are where silent errors hide. If the ontology
states them, validation can catch them and conversion can adapt them.

## P1 - One canonical term per concept

The adapter currently accepts `GrossFloorArea`, `GroundFloorArea`, `floor_area`, `GEBF`
for the same idea. That flexibility was useful for a quick integration, but long term it
is drift. Decide the canonical ontology term for each concept and use it everywhere.
Promote attributes that recur across two or more workpackages from extensions into the
core ontology (the extension model already calls for this).

Why it matters: a shared vocabulary only pays off if everyone uses the same words.

## P1 - Shapes (SHACL) for "what a model requires"

Move from "these attribute classes exist" to "a Building used by service X must have
these attributes, with these units, in these ranges". SHACL shapes are the rigorous
version of the requirements template, and they can validate a scenario directly against
the graph.

Why it matters: it makes the requirement machine-checkable and reusable, rather than a
YAML template that only the converter understands.

## P2 - Reference data sources, do not carry them

Digicities supplies static structure and configuration; the live timeseries stay in the
RDP stack (the optimizer pulls weather from Redis, not from us). That division is
correct and should be protected.

Strengthen the link rather than blur it: let an attribute reference a data source or
timeseries by URI (a pointer into TimescaleDB, a Redis stream, or a data product),
using the existing time-series-reference attributes. Then a scenario can say "this
building's heat demand is this data product" without the numbers ever passing through
the graph.

Why it matters: this is the other half of "connect raw data to services", done without
turning the knowledge graph into a timeseries database (which it should never be).

Progress: the configuration half is now explicit. A value that sets a boundary
condition of a model run (a model choice, a calibration constant)
is a `ConfigurationAttribute` in a `ServiceConfiguration` profile owned by the
service, kept apart from the components' own attributes (since core ontology v0.5.0). A live data stream that delivers a component's values is not configuration: it belongs to that component, as the `hasLiveTimeSeriesReference` of one of its attributes.

## P2 - Bring results back into the graph

Today results come back as JSON and are displayed or filed. To act as the brain,
ingest the model's output as linked data tied to the scenario and building URIs, so an
optimization run becomes a first-class, queryable thing. Then you can compare runs,
trace provenance ("this result came from this scenario, this model, this data"), and
query across results.

Why it matters: it closes the loop. Inputs and outputs live in the same described world.

## P3 - A service / requirements registry and discovery

We already share service definitions through `service_catalog`. Extend that into a
proper registry of available models and what each one needs, so a user can ask "what
can I run on this building?" and the platform can answer, and tell them what is missing.
A first step is in place: each workspace's service requirements and configuration
profiles are loaded into its `<http://services>` graph, so they are queryable.

## P3 - Lint the ontology and example scenarios in CI

Add checks that extensions parse and are well formed (attributes hang off the right
parents, components are subclasses of `Component`, no dangling references), and that the
shipped example scenarios still convert and validate. This catches the class of problem
we hit where `Building` was not declared a `Component` and silently vanished from the UI.

## Bottom line

The concept is strong and well placed. The two changes that matter most are: **enforce
the contracts** (validation), and **keep the meaning in the ontology and templates, not
in per-service code**. Do those and Digicities stops being "a vocabulary we have" and
becomes "the vocabulary the stack runs on".
