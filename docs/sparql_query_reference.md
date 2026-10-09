# Digicities — SPARQL Query Reference

This document describes the RDF triple patterns produced by the Digicities Replica Builder and provides ready-to-use SPARQL queries for accessing component and attribute data.

---

## Graph Model

Each workspace's dataset keeps its data in **named graphs**, and the default graph is left empty (provisioning clears it). The graph names are defined once in `backend/graphdb/graphs.py`:

| Named graph | What it holds |
|---|---|
| `<http://ontology_dici_onto>` | Core ontology + the workspace's extensions (the schema) |
| `<http://classes_and_attributes>` | Component instances, their attribute nodes and TimeSeries resources |
| `<http://system_description>` | Component-to-component relationships |
| `<http://scenarios>` | Scenarios |
| `<http://services>` | Registered services: their requirements and configuration profiles (from `services/*.ttl`) |
| `<http://collections>` | Derived sets, statistics and projected aggregates (computed, never authored) |
| `<http://inferred/ontology_dici_onto>`, `<http://inferred/classes_and_attributes>`, `<http://inferred/services>` | What the platform's reasoner derived from the graph of the same name (super-classes, super-properties, inverses). See [`INFERENCE.md`](INFERENCE.md). |

**Name the graphs a query reads with `FROM` clauses.** That makes their union the query's default graph and returns the same rows on Fuseki and GraphDB. A query with no `FROM` (and no `GRAPH` pattern) reads the empty default graph and returns nothing on Fuseki. The examples below leave the `FROM` lines out for brevity; add these to each:

```sparql
FROM <http://ontology_dici_onto>
FROM <http://inferred/ontology_dici_onto>
FROM <http://classes_and_attributes>
FROM <http://inferred/classes_and_attributes>
FROM <http://system_description>
```

The `inferred/` graphs hold what the reasoner derived. Many examples below rely on it:
`?x dici_onto:hasAttribute ?attr` matches a typed predicate such as
`hasWindTurbineHubHeightAttribute` only through the derived super-property. Leave the
`inferred/` lines out when you want only what was asserted, for example "which link did the
user choose". (Platform code builds the same block with
`backend.graphdb.graphs.from_clause(...)`; `inferred=False` drops the companions.)

---

## Namespace Prefixes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt:      <http://qudt.org/schema/qudt/>
PREFIX unit:      <http://qudt.org/vocab/unit/>
PREFIX dcterms:   <http://purl.org/dc/terms/>
PREFIX xsd:       <http://www.w3.org/2001/XMLSchema#>
PREFIX cur:       <http://qudt.org/vocab/currency/>
PREFIX rdfs:      <http://www.w3.org/2000/01/rdf-schema#>
```

---

## 1. Component Instance Structure

Every component instance follows this pattern:

```turtle
<{instance_uri}> a dici_onto:{ComponentType} ;
    rdfs:label "{label}" ;
    dici_onto:hasAttribute <{attr_uri_1}>, <{attr_uri_2}>, ... ;
    dici_onto:has{ComponentType}{AttributeName}Attribute <{attr_uri_1}> ;
    dici_onto:has{ComponentType}{AttributeName}Attribute <{attr_uri_2}> .
```

Attribute URIs follow the pattern: `{instance_uri}/{AttributeName}`

### Query: All component instances with their type and label

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?type ?label
WHERE {
    ?instance a ?type ;
        rdfs:label ?label .
    FILTER NOT EXISTS { ?type a ?type }  # exclude attribute resources
}
ORDER BY ?type ?label
```

### Query: All instances of a specific component type

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?label
WHERE {
    ?instance a dici_onto:Building ;   # replace with desired ComponentType
        rdfs:label ?label .
}
```

### Query: All attributes belonging to a component instance

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?label ?attribute
WHERE {
    ?instance a dici_onto:Building ;
        rdfs:label ?label ;
        dici_onto:hasAttribute ?attribute .
}
```

---

## 2. Physical Attribute

Static (no time series) — typed as `dici_onto:PhysicalAttribute`:

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:PhysicalAttribute ;
    qudt:unit <http://qudt.org/vocab/unit/{UnitCode}> ;
    dici_onto:hasUnitLabel "{UnitCode}"^^xsd:string ;
    qudt:value "{decimal}"^^xsd:decimal ;
    dcterms:source "{source}"^^xsd:string .
```

Dynamic (has time series) — typed as `dici_onto:DynamicAttribute`:

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:DynamicAttribute ;
    qudt:unit <http://qudt.org/vocab/unit/{UnitCode}> ;
    dici_onto:hasUnitLabel "{UnitCode}"^^xsd:string ;
    qudt:value "{decimal}"^^xsd:decimal ;
    dici_onto:hasHistoricTimeSeries <{attr_uri}_historic/ts> ;
    dici_onto:hasHistoricTimeSeriesReference "{file_path}"^^xsd:string ;
    dici_onto:hasFutureTimeSeries <{attr_uri}_future/ts> ;
    dici_onto:hasFutureTimeSeriesReference "{file_path}"^^xsd:string ;
    dici_onto:hasLiveTimeSeries <{attr_uri}_live/ts> ;
    dici_onto:hasLiveTimeSeriesReference "{endpoint}"^^xsd:string .
```

### Query: All Physical attributes with their values and units

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?instance ?instanceLabel ?attrName ?value ?unit
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:PhysicalAttribute ;
        dici_onto:hasUnitLabel ?unit .
    OPTIONAL { ?attr qudt:value ?value }
    BIND(STRAFTER(STR(?attr), STR(?instance)) AS ?attrName)
}
```

### Query: All Dynamic attributes with their time series file references

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?historicFile ?futureFile ?liveEndpoint
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:DynamicAttribute .
    OPTIONAL { ?attr dici_onto:hasHistoricTimeSeriesReference ?historicFile }
    OPTIONAL { ?attr dici_onto:hasFutureTimeSeriesReference  ?futureFile }
    OPTIONAL { ?attr dici_onto:hasLiveTimeSeriesReference    ?liveEndpoint }
}
```

### Query: Fetch TimeSeries resources for a specific attribute

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt: <http://qudt.org/schema/qudt/>

SELECT ?ts ?storedAt ?fileName ?unit
WHERE {
    <{attr_uri}> dici_onto:hasHistoricTimeSeries ?ts .
    ?ts dici_onto:storedAt ?storedAt ;
        dici_onto:hasFileName ?fileName .
    OPTIONAL { ?ts dici_onto:hasUnitLabel ?unit }
}
```

For **live** TimeSeries, use `dici_onto:hasLiveTimeSeries` and `dici_onto:realTimeSource` instead:

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>

SELECT ?ts ?realTimeSource ?unit
WHERE {
    <{attr_uri}> dici_onto:hasLiveTimeSeries ?ts .
    ?ts dici_onto:realTimeSource ?realTimeSource .
    OPTIONAL { ?ts dici_onto:hasUnitLabel ?unit }
}
```

---

## 3. Categorical Attribute

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:CategoricalAttribute ;
    dici_onto:hasCategoricalValue dici_onto:{CategoryValue} .   # an IRI, never a literal or an extra rdf:type
```

### Query: All Categorical attributes with their values

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?categoryValue
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:CategoricalAttribute ;
        dici_onto:hasCategoricalValue ?categoryValue .
}
```

---

## 4. Event Attribute

Temporal precision controls the XSD type of `dici_onto:hasTemporalValue`:

| `dici_onto:hasTemporalPrecision` | XSD type | Example value |
|----------------------------------|----------|---------------|
| `dici_onto:Year` | `xsd:gYear` | `"1985"` |
| `dici_onto:YearMonth` | `xsd:gYearMonth` | `"1985-03"` |
| `dici_onto:Date` | `xsd:date` | `"1985-03-15"` |
| `dici_onto:DateTime` | `xsd:dateTime` | `"1985-03-15T12:00:00"` |

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:EventAttribute ;
    dici_onto:hasTemporalPrecision dici_onto:Year ;
    dici_onto:hasTemporalValue "1985"^^xsd:gYear ;
    dcterms:source "{source}"^^xsd:string .
```

### Query: All Event attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?precision ?temporalValue
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:EventAttribute ;
        dici_onto:hasTemporalPrecision ?precision ;
        dici_onto:hasTemporalValue ?temporalValue .
}
```

---

## 5. SimpleCost Attribute

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:SimpleCostAttribute ;
    qudt:value "{decimal}"^^xsd:decimal ;
    dici_onto:currency cur:CHF ;
    dcterms:source "{source}"^^xsd:string .
```

### Query: All SimpleCost attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?value ?currency
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:SimpleCostAttribute ;
        qudt:value ?value ;
        dici_onto:currency ?currency .
}
```

---

## 6. UnitBasedCost Attribute

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:UnitBasedCostAttribute ;
    qudt:value "{decimal}"^^xsd:decimal ;
    qudt:unit <http://qudt.org/vocab/unit/{UnitCode}> ;
    dici_onto:hasUnitLabel "{UnitCode}"^^xsd:string ;
    dici_onto:currency cur:CHF ;
    dcterms:source "{source}"^^xsd:string .
```

### Query: All UnitBasedCost attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?value ?unit ?currency
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:UnitBasedCostAttribute ;
        qudt:value ?value ;
        dici_onto:hasUnitLabel ?unit ;
        dici_onto:currency ?currency .
}
```

---

## 7. Curve Attribute

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:CurveAttribute ;
    dici_onto:xUnit unit:{XUnitCode} ;
    dici_onto:xUnitLabel "{XUnitCode}"^^xsd:string ;
    dici_onto:yUnit unit:{YUnitCode} ;
    dici_onto:yUnitLabel "{YUnitCode}"^^xsd:string ;
    dici_onto:hasDataPoints """[
        [   1.0,        2.5],
        [   2.0,        4.0]
    ]""" ;
    dcterms:source "{source}"^^xsd:string .
```

`dici_onto:hasDataPoints` is a multi-line triple-quoted string containing a JSON-style array of `[x, y]` pairs. Numbers are formatted as decimals (e.g., `1.0`).

### Query: All Curve attributes with units

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?xUnit ?yUnit ?dataPoints
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:CurveAttribute ;
        dici_onto:xUnitLabel ?xUnit ;
        dici_onto:yUnitLabel ?yUnit ;
        dici_onto:hasDataPoints ?dataPoints .
}
```

---

## 8. Data path (Resource) Attribute

The value kind is `DataPathAttribute` (core v0.6.0). `ResourceAttribute` is only the
category of the `Resource` component; data typed only `ResourceAttribute` comes from
before v0.6.0 and is rebuilt on the next onboarding.

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:DataPathAttribute ;
    dici_onto:hasDataPath "{file_or_resource_path}"^^xsd:string .
```

### Query: All data path attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?dataPath
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:DataPathAttribute ;
        dici_onto:hasDataPath ?dataPath .
}
```

---

## 9. SimpleValue Attribute

The value is stored as `xsd:decimal` if numeric, otherwise `xsd:string`.

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:SimpleValueAttribute ;
    dcterms:source "{source}"^^xsd:string ;
    dici_onto:hasAttributeValue "{value}"^^xsd:decimal .
```

### Query: All SimpleValue attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?value
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:SimpleValueAttribute ;
        dici_onto:hasAttributeValue ?value .
}
```

---

## 10. CustomPhysicalRatio Attribute

Ratio units (e.g., kWh/m²) cannot be expressed as a single QUDT unit IRI. Therefore `dici_onto:hasUnitLabel` is used **exclusively** — there is no `qudt:unit` triple for this type.

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:CustomPhysicalRatioAttribute ;
    dcterms:source "{source}"^^xsd:string ;
    qudt:value "{decimal}"^^xsd:decimal ;
    dici_onto:hasUnitLabel "KiloW-HR/M2"^^xsd:string .
```

`dici_onto:hasUnitLabel` format: `"{NumeratorUnit}/{DenominatorUnit}"` using QUDT local names (e.g., `"KiloW-HR/M2"`, `"KiloW-HR/DEG_C"`).

### Query: All CustomPhysicalRatio attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?value ?unitLabel
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:CustomPhysicalRatioAttribute ;
        qudt:value ?value ;
        dici_onto:hasUnitLabel ?unitLabel .
}
```

To split numerator and denominator in SPARQL:

```sparql
BIND(STRBEFORE(?unitLabel, "/") AS ?numeratorUnit)
BIND(STRAFTER(?unitLabel, "/")  AS ?denominatorUnit)
```

---

## 11. Identifier Attribute

```turtle
<{identifier_uri}> a dici_onto:{AttributeName} ;
    dici_onto:identifierValue "{id_string}" .
```

The component instance also carries:
```turtle
<{instance_uri}> dici_onto:hasIdentifier <{identifier_uri}> .
```

Note: `dici_onto:identifierValue` is a plain literal (no explicit xsd type).

### Query: All Identifier attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?idValue
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasIdentifier ?identifier .
    ?identifier dici_onto:identifierValue ?idValue .
}
```

---

## 12. Geospatial Attribute

```turtle
<{attr_uri}> a dici_onto:{AttributeName} ;
    a dici_onto:GeospatialAttribute ;
    dcterms:source "{source}"^^xsd:string ;
    qudt:unit <http://qudt.org/vocab/unit/{UnitCode}> ;
    dici_onto:hasUnitLabel "{UnitCode}"^^xsd:string ;
    dici_onto:hasAttributeValue "{geospatial_value}"^^xsd:string .
```

### Query: All Geospatial attributes

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?instanceLabel ?attr ?value ?unit
WHERE {
    ?instance rdfs:label ?instanceLabel ;
        dici_onto:hasAttribute ?attr .
    ?attr a dici_onto:GeospatialAttribute ;
        dici_onto:hasAttributeValue ?value .
    OPTIONAL { ?attr dici_onto:hasUnitLabel ?unit }
}
```

---

## 13. ClassObject Relationships (system_description)

ClassObject attributes do **not** create a separate attribute resource. Instead they generate a direct predicate on the component instance, stored in `<http://system_description>`:

```turtle
<{source_instance_uri}> dici_onto:{predicate} <{target_instance_uri}> .
```

### Query: All inter-component relationships

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?source ?sourceLabel ?predicate ?target ?targetLabel
WHERE {
    ?source ?predicate ?target .
    FILTER(STRSTARTS(STR(?predicate), "https://digicities.info/ontology#"))
    OPTIONAL {
        ?source rdfs:label ?sourceLabel .
        ?target rdfs:label ?targetLabel .
    }
}
```

### Query: Neighbours of a specific instance

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?predicate ?neighbour ?neighbourLabel
WHERE {
    { <{instance_uri}> ?predicate ?neighbour }
    UNION
    { ?neighbour ?predicate <{instance_uri}> }
    OPTIONAL {
        ?neighbour rdfs:label ?neighbourLabel .
    }
}
```

---

## 14. Cross-Type Query: All attributes of all types for one instance

The following query returns every attribute of a component instance and pivots on the most common value fields. Use it as a starting point and extend per type as needed.

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt:      <http://qudt.org/schema/qudt/>
PREFIX rdfs:      <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?attr ?attrType ?numericValue ?unitLabel ?textValue ?temporalValue ?categoryValue
WHERE {
    <{instance_uri}> dici_onto:hasAttribute ?attr .
    ?attr a ?attrType .

    OPTIONAL { ?attr qudt:value                    ?numericValue }
    OPTIONAL { ?attr dici_onto:hasUnitLabel         ?unitLabel }
    OPTIONAL { ?attr dici_onto:hasAttributeValue    ?textValue }
    OPTIONAL { ?attr dici_onto:hasTemporalValue      ?temporalValue }
    OPTIONAL { ?attr dici_onto:hasCategoricalValue   ?categoryValue }
    FILTER(?attrType != rdfs:Resource)
}
ORDER BY ?attrType ?attr
```

---

## 15. Datasource / Provenance

Any attribute that has a data source carries:

```sparql
OPTIONAL { ?attr dcterms:source ?datasource }
```

Add this to any query to retrieve provenance.

---

## 16. Service configuration

A value that sets a boundary condition of a model run (a model choice, a calibration constant, a run name) is **configuration**, not a property of a component. A live data stream that delivers a component's values is not configuration: it belongs to that component, as the `hasLiveTimeSeriesReference` of one of its attributes. It is a `dici_onto:ConfigurationAttribute` node in a `dici_onto:ServiceConfiguration` profile owned by a `dici_onto:Service`, held in `<http://services>`:

```turtle
<{service_uri}> a dici_onto:Service ;
    dici_onto:hasConfiguration <{service_uri}/config/{profile}> .
<{service_uri}/config/{profile}> a dici_onto:ServiceConfiguration ;
    dici_onto:appliesTo <{component_uri}> ;                 # optional: the components it is tuned for
    dici_onto:hasConfigurationParameter <{service_uri}/config/{profile}/{Param}> .
<{service_uri}/config/{profile}/{Param}> a dici_onto:{Param}, dici_onto:ConfigurationAttribute ;
    qudt:value 0.0324555 .                                  # or hasAttributeValue / hasCategoricalValue
```

### Query: Configuration parameters that apply to one component

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX qudt: <http://qudt.org/schema/qudt/>

SELECT ?service ?profile ?paramClass ?num ?simple ?cat
FROM <http://ontology_dici_onto>
FROM <http://services>
WHERE {
    ?profile dici_onto:appliesTo <{component_uri}> ;
             dici_onto:hasConfigurationParameter ?param .
    OPTIONAL { ?service dici_onto:hasConfiguration ?profile }
    ?param a ?paramClass .
    ?paramClass rdfs:subClassOf* dici_onto:ConfigurationAttribute .
    FILTER(?paramClass != dici_onto:ConfigurationAttribute)
    OPTIONAL { ?param qudt:value ?num }
    OPTIONAL { ?param dici_onto:hasAttributeValue ?simple }
    OPTIONAL { ?param dici_onto:hasCategoricalValue ?cat }
}
```

---

## 17. Derived aggregates (statistics over linked components)

A statistic over the components linked to a container (the mean apple weight per tree, say) is computed by the Collections module and projected onto the container as an attribute node in `<http://collections>`: `{container_uri}/{Attr}{Stat}`, typed `dici_onto:{Attr}{Stat}` and `dici_onto:AggregateAttribute`, valued with `qudt:value`, and linked back to the Set it summarises with `dici_onto:aggregateOf`. `{Stat}` is one of `Mean`, `Median`, `Sum`, `MinValue`, `MaxValue`, `Count`, `StandardDeviation`. A service template requests it as `{Container}.{Attr}{Stat}` (for example `Tree.WeightMean`).

### Query: Derived aggregates on each container

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX qudt: <http://qudt.org/schema/qudt/>

SELECT ?container ?aggregate ?statistic ?value
FROM <http://collections>
WHERE {
    ?container dici_onto:hasAttribute ?aggregate .
    ?aggregate a dici_onto:AggregateAttribute ;
               dici_onto:statisticUsed ?statistic ;
               qudt:value ?value .
}
ORDER BY ?container ?aggregate
```

---

## 18. Summary: Property Reference

| Attribute type | `rdf:type` (in addition to `dici_onto:{AttrName}`) | Value predicate | Unit predicate | Notes |
|---|---|---|---|---|
| Physical (static) | `dici_onto:PhysicalAttribute` | `qudt:value` (decimal) | `qudt:unit` + `dici_onto:hasUnitLabel` | — |
| Physical (dynamic) | `dici_onto:DynamicAttribute` | `qudt:value` (decimal) | `qudt:unit` + `dici_onto:hasUnitLabel` | See `hasHistoricTimeSeries`, `hasFutureTimeSeries`, `hasLiveTimeSeries` |
| TimeSeries (historic/future) | `dici_onto:TimeSeries` | `dici_onto:storedAt`, `dici_onto:hasFileName` | `qudt:unit` + `dici_onto:hasUnitLabel` | Sub-resource of Dynamic attribute |
| TimeSeries (live) | `dici_onto:TimeSeries` | `dici_onto:realTimeSource` | `qudt:unit` + `dici_onto:hasUnitLabel` | Sub-resource of Dynamic attribute |
| Categorical | `dici_onto:CategoricalAttribute` | `dici_onto:hasCategoricalValue` (IRI, an object property) | — | Older data also typed the node `dici_onto:{CategoryValue}` |
| Event | `dici_onto:EventAttribute` | `dici_onto:hasTemporalValue` | — | `dici_onto:hasTemporalPrecision` controls XSD type |
| SimpleCost | `dici_onto:SimpleCostAttribute` | `qudt:value` (decimal) | `dici_onto:currency` | Currency only, no unit |
| UnitBasedCost | `dici_onto:UnitBasedCostAttribute` | `qudt:value` (decimal) | `qudt:unit` + `dici_onto:hasUnitLabel` + `dici_onto:currency` | — |
| Curve | `dici_onto:CurveAttribute` | `dici_onto:hasDataPoints` (string array) | `dici_onto:xUnit`/`xUnitLabel`, `dici_onto:yUnit`/`yUnitLabel` | x/y axis units separate |
| Resource (data path) | `dici_onto:DataPathAttribute` | `dici_onto:hasDataPath` (string) | — | — |
| SimpleValue | `dici_onto:SimpleValueAttribute` | `dici_onto:hasAttributeValue` (decimal or string) | — | — |
| CustomPhysicalRatio | `dici_onto:CustomPhysicalRatioAttribute` | `qudt:value` (decimal) | `dici_onto:hasUnitLabel` **only** (format: `"Num/Den"`) | No `qudt:unit` IRI |
| Identifier | `dici_onto:IdentifierAttribute` | `dici_onto:identifierValue` (plain literal) | — | Linked via `dici_onto:hasIdentifier` |
| Geospatial | `dici_onto:GeospatialAttribute` | `dici_onto:hasAttributeValue` (string) | `qudt:unit` + `dici_onto:hasUnitLabel` | — |
| ClassObject | — (direct predicate on instance) | `dici_onto:{predicate}` → target IRI | — | Stored in `<http://system_description>` |
