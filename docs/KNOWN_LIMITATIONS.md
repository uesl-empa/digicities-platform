# Known limitations

Applies to: **platform 0.5.0 plus the unreleased `fix/foundations` work** (it ships in the next
platform release) and **core ontology 0.6.0**.

This is the one list of what Digicities does not do yet, or does not do well. Other pages
link here instead of keeping their own list.

**How to keep it current.** Every entry says since which release it applies ("Since"). Review
the whole page before every release. When you find a new limitation, add it with what it is,
what it means for a user, since which release, and its status. When one is fixed, move it to
"Resolved" under the release that ships the fix, and delete that release's section once the
release after it is out. "The next platform release" means the first release that contains
the change; replace it with the version number when you tag the release.

## Requirements and validation

**Requirements are read by syntax, not against a schema.**
What: a service contract (`services/<Name>.yaml`) states its inputs as dotted strings
(`WindTurbine.HubHeight`, `CL.WindPark.WindTurbine`). The platform reads any template value
containing a dot as a requirement and any value starting with `CL.` as a link
(`backend/scenario_builder/requirements.py`). There is no schema for the language yet.
Impact: a constant that happens to contain a dot (a version number, a host name) is read as a
requirement. Mistakes in the contract show up late, at conversion.
Since: platform 0.5.0 or earlier.
Status: the language is specified in [`SERVICE_REQUIREMENTS_SPEC.md`](SERVICE_REQUIREMENTS_SPEC.md);
SHACL shapes for it are planned.

**Validation checks completeness, not values.**
What: `validate_payload` reports references that did not resolve and links that produced no
components. It does not check units, value types, ranges or allowed values.
Impact: a payload with every field present but a value in the wrong unit passes.
Since: platform 0.5.0 or earlier.
Status: planned as SHACL shapes (see [`SEMANTIC_LAYER.md`](SEMANTIC_LAYER.md)).

**The REST submit does not re-check validation.**
What: `POST .../submission/convert` returns the validation report, but `POST .../submission/submit`
only refuses an empty payload. The Streamlit Submit tab and the onboarding agent do block on
validation errors.
Impact: a client that ignores the convert report can submit an incomplete payload over REST.
Since: platform 0.5.0 or earlier.
Status: open.

**Service-side adapters can hide missing data.**
What: an adapter in front of a model (the flexibility optimiser's, for example) can match names
loosely and fill in defaults.
Impact: the model may return a confident answer for an incomplete input.
Since: platform 0.5.0 or earlier.
Status: open; the aim is a contract precise enough that adapters only move data.

## Ontology

**`hasSource` has two meanings.**
What: in the core, `hasSource` is a flow property (the component a `Flow` comes from). Some
platform code and tests also treat a record's `hasSource` as "where this record came from"
(provenance). The onboarding agent writes record sources with `hasDataSource`, which the
workspace extension declares, not the core.
Impact: provenance queries depend on extension declarations; a reasoner that reads the core
alone sees flows where there is provenance.
Since: core ontology 0.5.0 or earlier.
Status: planned. A core `hasReference` (under `prov:wasDerivedFrom`, range `Reference`) will
carry provenance, and `hasSource` stays the flow property.

**The core gives `qudt:unit` a domain.**
What: the core declares `qudt:unit` with `rdfs:domain dici_onto:Attribute` and as a
sub-property of `dici_onto:hasUnit`.
Impact: any QUDT data loaded next to Digicities data inherits Digicities meaning, and an
external reasoner that applies domains would type QUDT nodes as Digicities attributes.
Since: core ontology 0.5.0 or earlier.
Status: planned: drop both statements and keep `hasUnit` as Digicities' own property.

**Domain and range are not used for reasoning.**
What: by design, using a link never changes what a thing is, so `rdfs:domain` and `rdfs:range`
are kept as documentation and left out of the reasoner (see [`INFERENCE.md`](INFERENCE.md)).
Impact: a tool that expects RDFS domain/range typing will not find it in Digicities data.
Since: platform 0.5.0 or earlier.
Status: deliberate.

**No resolvable IRIs and no DOI yet.**
What: `https://digicities.info/ontology#` terms do not resolve in a browser, and releases have
no DOI.
Impact: harder to cite and to look terms up.
Since: core ontology 0.5.0 or earlier.
Status: planned (a persistent IRI service such as w3id.org, and a Zenodo DOI per release).
Changing IRIs needs a migration plan.

## Scenarios and assumptions

**Overrides from one scenario can leak into another.**
What: when the platform materialises a scenario from the shared scenarios graph
(`construct_scenario_ttl`), it collects every `supersedesAttribute` override in that graph,
not only the ones of the scenario it is building (`backend/graphdb/queries/scenarios.py`).
Impact: two scenarios that override the same attribute can show each other's values in the
materialised view.
Since: platform 0.5.0 or earlier.
Status: planned fix: only the overrides used by the scenario being built, with a test of two
scenarios overriding one attribute.

**Scenario lineage is one level deep.**
What: a scenario records the scenario it is based on (`basedOn`), but nothing follows that link,
and `basedOn` is not declared as provenance.
Impact: a 2040 scenario based on a 2030 scenario based on the baseline does not pick up the
2030 changes.
Since: platform 0.5.0 or earlier.
Status: planned: follow `basedOn` recursively (with a guard against cycles) and declare it
under `prov:wasDerivedFrom`.

**Sub-scenarios can only change attribute values.**
What: a scenario cannot add, remove or replace components, and the assumption tools do not
cover curves, events or data-path attributes. An assumption is not a node of its own in the
graph.
Impact: "what if we add two turbines" has to be built by hand.
Since: platform 0.5.0 or earlier.
Status: planned, needs design decisions.

## Data and onboarding

**The onboarding agent's mapping proposals vary between runs.**
What: records and configuration are now read by code (the extraction plan, every key of the
configuration files), but the classes, parents and links are proposed by a language model.
Impact: two onboardings of the same folder can propose different class names or links. Every
proposal is shown as a decision for the user to confirm.
Since: platform 0.5.0 or earlier.
Status: by design for proposals; the decisions are what make the result the user's.

**Configuration parameter names come from the configuration file's keys.**
What: `model_parameters.k` becomes `ModelParametersK`.
Impact: names are reproducible but not always readable.
Since: the next platform release (unreleased).
Status: deliberate; a parameter can be annotated with a label.

**A secret written literally in a configuration file is only left out if the user confirms it.**
What: empty values and `${ENV}` placeholders are recorded as "set at deployment" and never
stored. A literal password is stored unless the agent proposes to leave it out and the user
agrees.
Impact: a literal secret can end up in the services graph if nobody notices the proposal.
Since: the next platform release (unreleased).
Status: open; keep secrets out of configuration files (use `${ENV}` placeholders).

**The Excel import is strict.**
What: every column of a workbook must have its link declared in the workspace extension first;
column headers that are not valid class names are renamed (`CAPEX_energy` becomes
`CAPEXEnergy`) and the rename is reported.
Impact: an older workbook may need its extension built first (the Ontology Manager does this).
Since: the next platform release (unreleased).
Status: deliberate: the converter never makes up a predicate.

**Workspaces built before core 0.6.0 need rebuilding.**
What: older extensions follow the Ontology Manager's old pattern, and older stores keep the
reasoner's output in the same graphs as the asserted data.
Impact: queries that read only asserted data see extra triples in those stores.
Since: the next platform release (unreleased) and core ontology 0.6.0.
Status: re-provision the workspace, and re-onboard or replay its extension instructions.

## Code quality

**Error handling and hand-built Turtle are still being cleaned up.**
What: a test (`tests/test_code_debt_ratchet.py`) counts these per file and only lets them go
down. In the next platform release: platform 543 broad `except`, 114 silent `except`, 233
f-string Turtle lines; onboarding agent 169, 68 and 14.
Impact: some failures are still swallowed instead of reported.
Since: platform 0.5.0 or earlier.
Status: being reduced module by module; new code cannot add any.

**A missing reasoner library is only printed.**
What: if `owlrl` is not installed, provisioning prints a message and skips the reasoner
(`backend/workspace/inference.py`).
Impact: queries that need derived triples return less, with no error.
Since: platform 0.5.0 or earlier.
Status: planned: make it an error. `owlrl` is in `requirements.txt`, so this only happens in
an old image.

## Resolved

### In the next platform release (unreleased) and core ontology 0.6.0

- A categorical value is an IRI: `hasCategoricalValue` is an object property pointing at the
  category (a named individual of the attribute's class), and every writer states it.
- Instances carry their record id as `rdfs:label`, and typed instance names are matched by label.
- String matching on class and predicate names removed from platform and agent; a test now bans
  it (`test_no_string_matching_in_code`).
- Derived triples live in their own graphs (`http://inferred/...`), so the graph a user built
  holds exactly what they asserted.
- `locatedIn` and `hasLocation` no longer collapse into each other under reasoning (`locatedIn`
  has its own inverse, `locationContains`).
- A materialised scenario no longer carries collection bookkeeping; it carries only the derived
  values its contract asks for.
- A data stream that feeds a component (a weather feed) is modelled as that component's live
  time series, and the contract links to it (`CL.WindPark.Weather`).
- Configuration extraction is deterministic: every key of the configuration files.
- The core ontology is built by the Ontology Manager from `bare_core.ttl` and
  `scaffold_instructions.json`, so core and extensions follow one pattern.
