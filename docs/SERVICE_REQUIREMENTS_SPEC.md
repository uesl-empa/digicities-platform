# The service-requirements language: specification

**Status:** normative description of the language as the platform implements it on
`fix/foundations` (October 2026). Every rule names the code it comes from in a
**Source** line, so the text can be checked against the implementation. Where the
code is inconsistent or leaves something undefined, the rule says so and section 13
lists it as an open issue. Nothing in this document is aspirational, except section
12 (SHACL), which is marked as planned.

**Audience:** people who write or check a service contract, and people who need a
precise reference for the mechanism (for example, a paper). For a step-by-step guide,
read [INTEGRATING_A_SERVICE.md](INTEGRATING_A_SERVICE.md) instead.

## 1. Conventions

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are used as in RFC 2119.

A *contract* is one service-requirements document: a YAML file in a workspace's
`services/` folder. A *payload* is what the platform sends to the service for one
scenario. A *scenario* is the RDF graph the contract is resolved against.

Every YAML example in this document starts with a marker comment, and
`tests/test_service_requirements_spec.py` checks each one against the platform's own
parser:

| Marker | Meaning, as checked by the test |
|---|---|
| `# example: valid` | The platform parses it, and the requirement extraction and connection reader accept it. |
| `# example: rejected` | The platform's parser refuses it with an error. |
| `# example: not caught` | Wrong, but the platform accepts it without an error. Section 10 explains each one. |
| `# example: fragment` | Part of a document. Only checked to be valid YAML. |

## 2. What a contract is

A contract states the data a model needs to run, as a template of the payload it
wants. Each field has a name on the left (what the model reads) and a reference on
the right (where Digicities finds the value in the knowledge graph). The platform
resolves the references for one scenario and sends the result.

The running example is the wind power forecaster: a wind park, its turbines, and the
weather stream the park is linked to.

```yaml
# example: valid
service_name: WindForecast
description: Wind power forecaster for one park
connection:
  transport: redis
  host: redis
  port: 6379
  result_stream: windforecast.eolica.Alkmaar
scenario_data:
  uri: Scenario.URI
  label: Scenario.label
  windPark:
    name: WindPark.label
    uri: WindPark.URI
    Roughness: WindPark.Roughness
    windTurbine:
      link: CL.WindPark.WindTurbine
      template:
        uri: WindTurbine.URI
        HubHeight: WindTurbine.HubHeight
        RotorDiameter: WindTurbine.RotorDiameter
        PowerCurve: WindTurbine.PowerCurve
    weather:
      link: CL.WindPark.Weather
      template:
        uri: Weather.URI
        WindspeedForecast_live: Weather.WindspeedForecast.hasLiveTimeSeriesReference
```

For a scenario with one park, two turbines and one weather stream, the payload is:

```json
{
  "service_name": "WindForecast",
  "description": "Wind power forecaster for one park",
  "scenario_data": {
    "uri": "https://digicities.info/proj/ws/Scenario/baseline",
    "label": "Baseline",
    "windPark": [
      {
        "name": "WindparkAlkmaar",
        "uri": "https://digicities.info/proj/ws/WindPark/Alkmaar",
        "Roughness": 0.1,
        "windTurbine": [
          {"uri": ".../WindTurbine/Alkmaar_1", "HubHeight": 80.0, "RotorDiameter": 71.0,
           "PowerCurve": {"points": [[3.0, 0.0], [12.0, 2300.0]], "x_unit": "M-PER-SEC", "y_unit": "KiloW"}},
          {"uri": ".../WindTurbine/Alkmaar_2", "HubHeight": 80.0, "RotorDiameter": 71.0}
        ],
        "weather": [
          {"uri": ".../Weather/weather_forecasts_openmeteo_Alkmaar",
           "WindspeedForecast_live": "weather.forecasts.openmeteo.Alkmaar"}
        ]
      }
    ]
  }
}
```

The weather stream is not special. It is a component (`Weather`) whose attribute
(`WindspeedForecast`) is a live time series. The stream address is that attribute's
`hasLiveTimeSeriesReference` in the replica, and the contract asks for it like any
other value.

## 3. Grammar

```ebnf
contract        = mapping of top-level-key to its value ;
top-level-key   = "service_name"          (* MUST, a non-empty string *)
                | "description"           (* MAY, free text *)
                | "connection"            (* MAY, see section 7 *)
                | "scenario_data"         (* MUST to produce a payload, a block *)
                | "optional_attributes"   (* MAY, list of attribute-ref *)
                | "derived_attributes"    (* MAY, list of attribute-ref *)
                | "required_attributes" ; (* MAY, list of field names *)

block           = mapping of field-name to value ;
value           = reference | literal | block | link-block | list of value ;
link-block      = mapping with "link" : link-ref , "template" : block ,
                  and any number of further field-name : link-block ;

link-ref        = "CL." , class-token , "." , class-token ;
reference       = scenario-ref | class-token , "." , member ;
scenario-ref    = "Scenario.URI" | "Scenario.label" ;
member          = identity | attribute-token , [ "." , property-token ] ;
identity        = "URI" | "label" ;           (* matched without regard to case *)
attribute-ref   = class-token , "." , attribute-token ;

class-token     = local-name ;                (* a dici_onto: class *)
attribute-token = local-name ;                (* a dici_onto: attribute class *)
property-token  = local-name ;                (* a dici_onto: property *)
local-name      = letter-or-underscore , { letter | digit | "_" | "-" } ;
field-name      = any YAML mapping key ;
literal         = any YAML scalar that is not a reference in its context ;
```

**Source:** `backend/api_submission/ttl_converter.py` (`RobustTTL2YAMLProcessor._term`,
`_process_value`, `_process_link`, `_resolve_string_value`),
`backend/service_requirements/template.py` (`build_service_template`,
`parse_yaml_to_components`).

A token names the `dici_onto:` IRI with that local name: `WindTurbine` names
`https://digicities.info/ontology#WindTurbine`. A token that is not a valid local name
names nothing. A link-ref MUST have exactly three dot-separated parts.

**Source:** `ttl_converter.py` `_term` (the `_LOCAL_NAME` pattern), `_process_link`.

## 4. Field expressions

### 4.1 Scenario fields

`Scenario.URI` resolves to the scenario's IRI. `Scenario.label` resolves to its
`rdfs:label`, or the last segment of its IRI when it has none.

**Source:** `ttl_converter.py` `_resolve_string_value`.

### 4.2 Identity fields

Inside a block for class `T`, `T.URI` resolves to the current instance's IRI, and
`T.label` to its `rdfs:label` (or the last segment of its IRI when it has none). The
member name is compared without regard to case, so `T.uri` works. A root block
SHOULD carry `name: T.label` and `uri: T.URI`, and a link-block's template SHOULD
carry `uri: T.URI`, because the template parser uses them to recognise blocks.

**Source:** `ttl_converter.py` `_resolve_string_value`; `template.py`
`build_service_template`, `parse_yaml_to_components`.

### 4.3 Attribute fields

`T.A` resolves to the value of the current instance's attribute of class `A`: the
node the instance reaches through an attribute edge (a predicate that is
`rdfs:subPropertyOf* dici_onto:hasAttribute`, or any edge to a node that is an
attribute) and that is an instance of `A` (`rdf:type`, then `rdfs:subClassOf*`). Only
that node is used. If the instance has no such node, the field has no value.

The value depends on the attribute's kind, read from the hierarchy:

| Kind | Value sent |
|---|---|
| Physical, SimpleCost, UnitBasedCost, Dynamic (a static value) | `qudt:value`, as a number when its datatype is numeric |
| SimpleValue | `dici_onto:hasAttributeValue` |
| DataPath | `dici_onto:hasDataPath` |
| Categorical | `dici_onto:hasCategoricalValue`, else the category the attribute node is typed with |
| Curve | `{"points": [[x, y], ...], "x_unit": ..., "y_unit": ...}` from `dici_onto:hasDataPoints` |
| Event | the temporal value, rewritten as `01-01-<year>` when it holds a year (see issue 7) |

Units are not sent, except a curve's axis units.

**Source:** `ttl_converter.py` `_find_attribute`, `_extract_attribute_value`,
`_category_value`, `_convert_literal`; `backend/ontology_kinds.py` (`kind_of_node`).

### 4.4 Nested property fields

`T.A.p` resolves to a property of the attribute node. `p` MUST be a time series
reference property, that is `rdfs:subPropertyOf* dici_onto:hasTimeSeriesReference`
(`hasHistoricTimeSeriesReference`, `hasLiveTimeSeriesReference`,
`hasFutureTimeSeriesReference`). The value is read through `p` or any subproperty of
it, so `T.A.hasTimeSeriesReference` is met by a live reference. Any other property
resolves to nothing. Segments after `p` are ignored (see issue 4).

The generator names these fields `<A>_historic`, `<A>_live` and `<A>_future`.

**Source:** `ttl_converter.py` `_get_nested_attribute`; `template.py`
`attribute_field`, `TS_REFERENCE`.

### 4.5 Literals

A string that is not a reference in its context is sent unchanged. This includes a
string that has the reference shape but names a class other than the current
block's class: it is left as written and then removed by the clean step (section 9).

**Source:** `ttl_converter.py` `_resolve_string_value`, `clean_placeholder_values`.

## 5. Blocks and links

### 5.1 Root blocks

A block directly under `scenario_data` whose fields reference class `T` (the first
field that references a class with instances in the scenario decides `T`) becomes a
**list**: one entry per instance of `T` that the scenario links to. Each entry is the
block resolved with that instance as the current instance. When no instance of `T`
is linked to the scenario, the block yields no list and its references stay
unresolved.

**Source:** `ttl_converter.py` `_detect_implicit_component_type`,
`_find_components_for_context`.

### 5.2 Link blocks

A link-block `{link: CL.S.T, template: ...}` becomes a **list** of the instances of
`T` linked to the source instances, one entry per target, each resolved with that
target as the current instance. The source instances are:

1. the scenario, when `S` is `dici_onto:Scenario` or a subclass of it;
2. else the current instance, when it is an instance of `S`;
3. else every instance of `S` in the scenario.

A link is a `dici_onto:ComponentLink` node in the scenario graph
(`hasInputEntity` to `linksInputyEntityTo`). The platform follows it in **both
directions**. Duplicate targets are sent once. A link-block with no targets yields an
empty list. A link-block always yields a list, even for one target.

Further link-blocks MAY sit beside `link` and `template`, or inside `template`. Both
are resolved with each target as the current instance.

**Source:** `ttl_converter.py` `_process_link`, `_find_linked_components`,
`_build_indexes`.

### 5.3 Root blocks reached through a link

A root-level link-block (for example `rooms: {link: CL.Building.Room, ...}` beside
`building`) sends the rooms linked to the scenario's buildings side by side with the
building block, instead of nested in it.

**Source:** `template.py` `build_service_template` (the `linked_root` case).

### 5.4 Which block contains which

The language does not decide nesting. The contract's author (or the onboarding agent)
decides it when the contract is written. The agent nests the contained class inside
its container, and reads which side contains which from the meaning of the link
predicate in the ontology: `partOf`, `locatedIn`, `hasLocation` and `locatedAt` put
the owner inside the target; `contains`, `hasPart`, `locationOf` and
`locationContains` put the target inside the owner.

At conversion, `CL.WindPark.WindTurbine` and `CL.WindTurbine.WindPark` find the same
pairs, because links are followed in both directions.

**Source:** agent `onboarding_agent/core/template_bridge.py` (`_type_edges`), agent
`core/builder.py` (`owner_contains`); `ttl_converter.py` `_find_linked_components`.

## 6. Optional, derived and required inputs

Three optional top-level lists change how strictly a contract is checked. Their
defaults are opposite in the two checks that read them (see issue 1).

### 6.1 In the Scenario Builder (completeness gate)

Every attribute a contract references is **required by default**. When a scenario is
built against the contract, an instance of a component type that lacks a value
(no value, or an empty string or list) for any required attribute is **left out of
the scenario**, with its links. `URI` and `label` are always met.

- `optional_attributes: [T.A, ...]` takes `T.A` out of the required set. The field
  stays in the payload; an instance without a value is sent without that field.
- `derived_attributes: [T.A, ...]` does the same, for values the platform computes at
  convert time (section 6.3).

The gate matches a component's type by its exact name, not by the hierarchy (see
issue 5).

```yaml
# example: valid
service_name: OrchardYield
scenario_data:
  uri: Scenario.URI
  tree:
    name: Tree.label
    uri: Tree.URI
    Variety: Tree.Variety
    WeightMean: Tree.WeightMean
    WeightStandardDeviation: Tree.WeightStandardDeviation
optional_attributes:
  - Tree.Variety
derived_attributes:
  - Tree.WeightMean
  - Tree.WeightStandardDeviation
```

**Source:** `backend/scenario_builder/requirements.py`
(`extract_required_attributes_enhanced`, `drop_optional_requirements`);
`backend/scenario_builder/emitter.py` (`get_filtered_components_for_ttl`,
`_requirement_absent`).

### 6.2 In payload validation

Every field is **optional by default**. A field whose reference does not resolve is a
warning. `required_attributes: [fieldName, ...]` makes the fields with those
**names** errors instead. The names are matched against the last part of the field's
path anywhere in the payload, not against `T.A` references (see issue 2).

**Source:** `backend/api_submission/validation.py` (`validate_payload`).

### 6.3 Derived values

A derived value is a statistic over the components linked to each instance:
`Tree.WeightMean` is the mean of `Apple.Weight` over the apples linked to each tree.
It is written `<Container>.<Attribute><Statistic>`, where the statistic is one of
`Mean`, `Median`, `Sum`, `MinValue`, `MaxValue`, `Count`, `StandardDeviation`. A
contract that uses one SHOULD list it under `derived_attributes`.

At convert time the platform computes the statistic in the Collections graph and
adds exactly the values the contract names to the scenario. The scenario never
receives any other collection data.

**Source:** `backend/collections/materializer.py` (`ensure_template_aggregates`,
`_STAT_SUFFIXES`); `backend/api_submission/materialize.py` (`derived_values`,
`materialize_against_workspace`).

## 7. The connection block

`connection` says where the service listens. It is registration data, and the
platform removes it before conversion, so it never reaches the payload. Values MAY use
`${VAR}` or `${VAR:-default}`, expanded from the environment.

```yaml
# example: fragment
connection:
  transport: http
  url: ${MODEL_URL:-http://host.docker.internal:8020/api/digicities/run}
  method: POST          # POST or PUT
  auth_type: none       # none | bearer | api_key | basic
  timeout: 120
```

```yaml
# example: fragment
connection:
  transport: redis
  host: redis
  port: 6379
  request_stream: windforecast.requests       # where the platform publishes
  result_stream: windforecast.eolica.Alkmaar  # where results are read
  timeout: 120
```

| Key | Transport | Default |
|---|---|---|
| `transport` | both | `http` |
| `url`, `method`, `headers`, `auth_type`, `auth_credentials`, `timeout` | http | `""`, `POST`, `{}`, `none`, `{}`, `60` |
| `host`, `port`, `request_stream`, `result_stream`, `payload_field`, `request_id_field`, `encode_payload_as_json`, `poll_timeout`, `timeout` | redis | `localhost`, `6379`, `""`, `""`, `payload`, `request_id`, `true`, `120`, `120` |

A Redis contract MAY omit `request_stream`. The platform then cannot start a run
(submission fails with an error) and can only read results. The connection block
MUST NOT list the streams a model reads its inputs from: a stream belongs to the
component it describes, through that component's live time series attribute
(section 2).

**Source:** `backend/api_submission/connection.py` (`resolve_connection`,
`expand_env`, `submit_via_connection`); `backend/api_submission/transports.py`
(`submit_redis`); `ttl_converter.py` `process` (removes `connection`).

## 8. Field names

The left side of a field is the name the model reads, and the contract's author MAY
choose it freely. The generator's defaults are:

| Field | Default name |
|---|---|
| a block | the class name in camelCase (`windPark`) |
| a static attribute `A` | `A` |
| a time series attribute `A` | `A_historic`, `A_live`, `A_future` |
| the root's label | `name` |
| an instance's IRI | `uri` |

A rename changes only the field name, never the reference. A child block never
carries its instance's label unless a rename asks for it, because the generator skips
a child's `label` field.

**Source:** `template.py` (`build_service_template`, `attribute_field`,
`list_template_fields`).

## 9. What is sent when a value is missing

A field whose reference does not resolve is left out of the payload. A block that
ends up empty is left out. Lists stay, possibly empty.

The top-level keys other than `connection` are copied into the payload: the
`service_name` and `description` strings, and the `optional_attributes`,
`derived_attributes` and `required_attributes` lists (see issue 3).

**Source:** `ttl_converter.py` (`process`, `clean_placeholder_values`).

## 10. Checks: what they guarantee, and what they do not

### 10.1 Parsing

The platform refuses a contract that is not valid YAML or has no `service_name`.

```yaml
# example: rejected
description: a contract without a service name
scenario_data:
  uri: Scenario.URI
```

Nothing else is refused when a contract is read. These are accepted without an
error:

```yaml
# example: not caught
service_name: BrokenLink
scenario_data:
  sites:
    link: CL.Site
    template:
      uri: Site.URI
```

A link-ref with two parts names no link. Reading the contract accepts it; only payload
validation later reports that the block found no components (section 10.3).

```yaml
# example: not caught
service_name: WrongNestedProperty
scenario_data:
  park:
    name: WindPark.label
    uri: WindPark.URI
    RoughnessUnit: WindPark.Roughness.hasUnitLabel
```

A nested property that is not a time series reference resolves to nothing
(section 4.4). Validation reports it as a warning.

**Source:** `template.py` `parse_yaml_to_components`, `parse_service_template`.

### 10.2 Scenario completeness gate

**Guarantees:** every component in a scenario built by the Scenario Builder against
a contract has a non-empty value for every attribute the contract requires of its
type (section 6.1), including nested time series references.

**Does not guarantee:** that the values are correct, in range or in the right unit;
that the required links exist; requirements on a superclass (issue 5); anything about
scenarios written by other tools (the onboarding agent writes its own baseline
scenarios and checks them with its own build gate).

**Source:** `emitter.py` `get_filtered_components_for_ttl`.

### 10.3 Payload validation

Validation runs on the converted payload before placeholders are removed.

**Guarantees:**
- An error for every link-block or root block that found no component.
- An error when the payload holds nothing besides `service_name` and `description`.
- For every field named in `required_attributes`: an error when its reference did
  not resolve or came back unchanged.
- A warning for every other field whose reference did not resolve.

The result is `is_valid` (no errors), the errors and warnings, and a data quality of
`good`, `needs_review` or `poor`.

**Does not catch:**
- Wrong values: units, ranges, datatypes, plausibility.
- A reference to a class or attribute that does not exist in the ontology. It just
  does not resolve, which is a warning unless the field is required.
- Why a link-block found nothing: a malformed link-ref (section 10.1), a class with
  no instances and a missing link all give the same error.
- A missing `request_stream` on a Redis contract.
- Duplicated or contradictory field names.

**Where it blocks:** the Streamlit submission refuses a payload that failed
validation. The REST `POST /submit` refuses only an empty payload (all component
lists empty), unless `force` is set (see issue 10).

**Source:** `validation.py` `validate_payload`, `ValidationResult`;
`apps/api/submission.py` (`convert`, `_hollow_payload_reason`, `submit`);
`apps/streamlit/components/api_submission_module/submission_core.py`.

### 10.4 The onboarding agent's build gate

When the onboarding agent builds a workspace, it converts the baseline scenario
exactly as submission does and compares the payload with the source data: every
instance and every value the source holds for what the service consumes must be in
the payload, or the build lists what is missing and submission is refused until the
user fixes or overrides it. This is a check of the agent's build, not of the
language.

**Source:** agent `onboarding_agent/core/payload_gate.py` (`check_payload`).

## 11. What the platform records from a contract

When a service is registered, the platform writes its requirements into the
workspace's `<http://services>` graph:

- one `dici_onto:Service` node;
- one `ComponentAttributeRequirement` per required attribute
  (`hasInputEntity` the class, `hasInputAttribute` the attribute class);
- one `ComponentComponentRequirement` per required link (two `hasInputEntity`);
- one `ComponentAttributeOutput` per output the model produces, with its result
  stream as `atStreamAddress`.

Configuration profiles (`ServiceConfiguration`, `hasConfigurationParameter`) live in
the same graph. They are not part of the contract YAML and are not sent in the
payload.

**Source:** `backend/service_requirements/requirements.py` (`requirements_ttl`); agent
`core/builder.py` (`_write_service`), agent `core/configuration.py`.

## 12. Relation to SHACL (planned, not implemented)

The language is checked today by the converter and the two checks in section 10.
A SHACL version is planned. It would state the same requirements as shapes, so any
SHACL validator could check a scenario without the converter. The mapping would be:

| Construct | SHACL |
|---|---|
| root block of class `T` | a node shape with `sh:targetClass dici_onto:T`, limited to instances linked to the scenario (a SPARQL-based target) |
| field `T.A` | a property shape on the attribute edge (`dici_onto:hasAttribute`, read with the inferred subproperty triples) with `sh:qualifiedValueShape [ sh:class dici_onto:A ]` |
| required (gate) | `sh:qualifiedMinCount 1`, plus a value shape (`qudt:value` or the kind's value property, `sh:minCount 1`) |
| optional | the same shape without a minimum count |
| `T.A.p` | a property shape on the attribute node with `sh:path p` and `sh:minCount 1` |
| link-block `CL.S.T` | a property shape on `S` whose path walks the scenario's ComponentLink nodes in both directions (`sh:alternativePath`), with `sh:class dici_onto:T` |

What SHACL would add that the language cannot state today:

- units and datatypes (`sh:datatype`, `qudt:unit` with `sh:in`);
- cardinality (exactly one hub height per turbine, at least one turbine per park);
- value ranges (`sh:minInclusive`, `sh:maxInclusive`);
- a standard validation report, published with the service in the services graph.

Derived values (section 6.3) need computed data, so they would stay outside plain
SHACL (SHACL rules or the current Collections step).

## 13. Open issues found while writing this specification

These are inconsistencies or gaps in the implementation. They are listed, not
resolved; each needs a decision.

1. **"Required" has opposite defaults.** The Scenario Builder treats every referenced
   attribute as required unless listed as optional or derived (section 6.1).
   Payload validation treats every field as optional unless its name is in
   `required_attributes` (section 6.2).
2. **Two meanings of `required_attributes`.** In a contract it is a list of payload
   field names, matched by the last part of the path anywhere in the payload, so two
   blocks with a field of the same name collide. In the requirement extraction's
   output (`parse_service_requirements`) the same key is a map from class to
   attributes.
3. **Control lists reach the payload.** `optional_attributes`, `derived_attributes`
   and `required_attributes` are copied into the payload sent to the service (the
   first two as empty lists after cleaning, the last one as written).
4. **Nested paths differ between modules.** The converter reads one time series
   reference property and ignores further segments; the Scenario Builder accepts any
   property and any depth.
5. **Type matching differs.** The converter matches classes through
   `rdfs:subClassOf*` (a requirement on `Turbine` finds wind turbines); the
   completeness gate matches the exact class name.
6. **Link direction and predicate are not part of resolution.** Conversion walks the
   scenario's ComponentLink nodes in both directions; the replica's link predicate
   plays no part. Nesting is decided only when the contract is written (section 5.4).
7. **Event values are shortened.** A temporal value holding a year is sent as
   `01-01-<year>`, dropping its month and day.
8. **The template parser reads names.** Reading a contract back
   (`parse_yaml_to_components`) takes a time series flavour from a field-name suffix
   (`_live`) or from the property name containing `Historic`, `Live` or `Future`, and
   decides a field's class with a substring test on the reference.
9. **Text that looks like a reference is removed.** The clean step drops any string
   containing `.URI` or `.label`, including free text.
10. **REST submission does not block on validation errors.** Streamlit refuses a
    payload that failed validation; `POST /submit` refuses only an empty one.
11. **Aggregates are found by name.** The platform finds derived values by the
    statistic suffix of the attribute name in every reference, not from the
    `derived_attributes` list.
12. **Three reference shapes.** The converter, the validator (`_REFERENCE_RE`, any
    capitalised `Class.member`) and the clean step (strict `Class.Attr`) each decide
    differently what counts as a reference.
13. **No version.** A contract carries no language version; changes to the language
    are visible only in the platform's history.

## 14. Versioning

The language has no version field (issue 13). This document describes the language
as implemented on the platform's `fix/foundations` branch. Changes to the language
are recorded in the platform's `CHANGELOG.md`.
