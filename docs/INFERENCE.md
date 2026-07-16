# Inference in Digicities

How the platform turns the asserted RDF in a workspace into the *queryable* RDF you see in the Query Manager, Component Explorer, and Data Products. And what that means for queries.

> Most users never need to read this. The platform handles inference automatically when a workspace is opened. Read on if you're curious about *why* `?x a dici_onto:Component` returns wind turbines and buildings, or if you're writing your own SPARQL.

## What gets inferred, when

When a workspace is opened, the platform's `ensure_workspace_repo` (in `backend/workspace/graphdb_provisioning.py`) does this:

1. Merges core ontology + workspace's `ontology/extensions/*.ttl` + `ingestion/output/*.ttl` + `scenarios/*.ttl` into an in-memory rdflib graph.
2. Runs an **RDFS-Plus closure** via `owlrl` (see `backend/workspace/inference.py`).
3. Writes the closed graph (asserted + inferred triples) to the active triplestore's default graph.

The default `rdfs-plus` profile materialises:

- `rdfs:subClassOf` transitive closure. `?inst a dici_onto:Component` catches every `WindTurbine`, `Building`, `EnergyConverter` instance without the query knowing the class hierarchy.
- `rdfs:subPropertyOf` transitive closure. `?inst dici_onto:hasAttribute ?attr` catches every typed attribute predicate (e.g. `hasBuildingGrossFloorArea`).
- `rdfs:domain` and `rdfs:range` propagation.
- `owl:equivalentClass`, `owl:equivalentProperty`, `owl:inverseOf` propagation.
- `owl:sameAs` and basic OWL property characteristics (`TransitiveProperty`, `SymmetricProperty`).

The closure runs **once per workspace open**, not per query. A one-time cost amortised over the session.

## Why materialise, instead of relying on the triplestore?

The platform supports two triplestore backends:

| Backend | Default? | Inference support |
|---|---|---|
| Apache Jena Fuseki (TDB2) | Yes (Apache-2.0) | None native |
| Ontotext GraphDB Free | Opt-in overlay | Configurable rulesets |

Materialising at write time means the same query returns the same results on either backend. Fuseki's lack of native inference becomes invisible. It also means workspace TTLs stay portable: nothing about the on-disk format is tied to a particular triplestore.

All triples land in the **default graph**. This sidesteps Fuseki's "default-graph only" SPARQL semantics vs GraphDB's "union of default + named graphs". A simple `?s ?p ?o` query returns the same rows on either.

## What this means for queries

The platform ships pre-written SPARQL with each module (Component Explorer, Data Products, etc.). If you write your own queries via the Query Manager UI, you get to lean on the materialised closure too:

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>

# Catches WindTurbine, Building, EnergyConverter, anything subClassOf* Component
SELECT ?inst WHERE { ?inst a dici_onto:Component }

# Catches every typed hasXAttribute predicate
SELECT ?attr WHERE { ?inst dici_onto:hasAttribute ?attr }
```

Avoid vendor-specific extensions if you want your queries to remain portable across backends:

```sparql
# AVOID: GraphDB-specific functions / prefixes
SELECT ?x WHERE { ?x ofn:hasShape <…> }       # GraphDB-only
```

Property paths still work and are valid as defence-in-depth if someone disables inference on a giant workspace:

```sparql
?inst ?p ?attr . ?p rdfs:subPropertyOf* dici_onto:hasAttribute .
```

## What's not materialised

The default profile is RDFS-Plus, not full OWL-DL. **Not** computed:

- Cardinality restrictions (`owl:maxCardinality`, etc.)
- Complex class restrictions (`owl:Restriction` with `owl:hasValue` / `owl:someValuesFrom` / `owl:allValuesFrom`)
- Disjointness consistency checking
- Classification (inferring class membership from property values)

If you need them:

1. **Use the `owl-rl` profile.** Change `materialize(merged, profile="owl-rl")` in `graphdb_provisioning.py`. Bigger closure (~10x to 20x more triples), slower provisioning.
2. **Switch to GraphDB with `owl-horst` or `owl-max` ruleset.** See `docker-compose.graphdb.yml`.
3. **Run a separate reasoner** (Jena's HermiT, Pellet) outside the triplestore and import the results.

## Performance tuning

| Workspace size | What to do |
|---|---|
| < 10k asserted triples | Default `rdfs-plus`. Closure runs in < 1 s. |
| 10k to 100k triples | Default `rdfs-plus`. Closure ~1 to 5 s on provisioning. Queries are instant. |
| 100k to 1M triples | Consider `rdfs` profile (faster) or `none` (rely on property paths). |
| > 1M triples | Switch to GraphDB Free, configure server-side ruleset. Provision-time closure becomes too slow. |

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Query returns rows on GraphDB, 0 on Fuseki | Query relies on GraphDB-default UNION semantics | Drop the `GRAPH` clause. Rely on the default graph. |
| Query returns 0 even after inference | Predicate has no `subPropertyOf` chain to `hasAttribute` | Add the chain in your extension TTL. Fix the model, not the query. |
| Subclass inference seems missing | `subClassOf` declaration on the class is itself missing | Same. Fix the extension. |
| Provisioning takes > 10 s on a small workspace | Closure is expensive for the data shape | Lower profile to `rdfs` or `none`. |
| `[inference] stripped N non-RDF-1.1-compliant triple(s)` warning | owlrl produced literal-subject edge-case triples | Safe to ignore. They're filtered before upload. |

## A note on extending the ontology

If you find that `?x a dici_onto:SomeClass` doesn't return what you expect, the answer is almost always to **extend the ontology**, not to rewrite the query. Add a subclass (or sub-property) declaration in your workspace's `ontology/extensions/`. The Ontology Manager UI does this for you. No SPARQL required. After the next workspace open, the platform re-materialises the closure and your query just works.

For how an extension concept eventually gets promoted back into the shared `dici_onto:` core, see [`digicities-ontology/docs/CORE_EVOLUTION.md`](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/CORE_EVOLUTION.md). It covers workspace, multi-workspace adoption, core release, with promotion criteria and the service-compatibility contract.
