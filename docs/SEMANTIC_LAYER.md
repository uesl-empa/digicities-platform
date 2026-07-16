# Strengthening Digicities as a semantic layer

Digicities earns its keep when it is the shared, self-describing vocabulary that sits
between raw data and the models that consume it. The flexibility-optimizer integration
proved the plumbing works end to end. This document is about the next mile: turning
"a demo that runs" into "a layer you can trust and reuse".

The honest current state: the integration works partly because the service-side
adapter is forgiving. It matches attribute names loosely and fills in defaults for
anything missing. That means today you can submit a half-described building and still
get a confident-looking but meaningless answer. The vocabulary exists, but nothing yet
guarantees that a scenario actually satisfies what a model needs before it is sent.

The work below closes that gap. It is ordered by leverage, not by effort.

## P0 - Enforce the contract (validation before submission)

This is the single highest-value change. Right now `ValidationResult` is defined in
the API submission module but never used.

Make it real: before a scenario is submitted, validate the converted payload against
the chosen service's requirements template and the ontology, and show the user:

- which required attributes are missing,
- which template references did not resolve (values still looking like
  `Building.PeakSpaceHeatingPower` instead of a number),
- which values fall outside the expected unit, type, or allowed set.

Block (or loudly warn before) submission when required fields are missing. The goal is
simple: a green tick should mean "this building genuinely has what the model needs",
not "we sent something and the service filled the blanks".

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
