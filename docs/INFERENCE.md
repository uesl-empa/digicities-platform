# Inference in Digicities

How the platform turns the asserted RDF in a workspace into the *queryable* RDF you see in the Query Manager, Component Explorer, and Data Products. And what that means for queries.

> Most users never need to read this. The platform handles inference automatically when a workspace is opened. Read on if you're curious about *why* `?x a dici_onto:Component` returns wind turbines and buildings, or if you're writing your own SPARQL.

## What gets inferred, when

When a workspace is opened, the platform's `ensure_workspace_repo` (in `backend/workspace/graphdb_provisioning.py`) does this:

1. Reads the core ontology + the workspace's `ontology/extensions/*.ttl` (the schema), `ingestion/output/*.ttl` (the instances), `scenarios/*.ttl` and `services/*.ttl` into in-memory rdflib graphs.
2. Runs an **RDFS-Plus closure** via `owlrl` (see `backend/workspace/inference.py`): once over the schema, once over schema + instances, and once over schema + services.
3. Writes what was **asserted** to each section's own named graph: the schema to `<http://ontology_dici_onto>`, the instances to `<http://classes_and_attributes>`, the services to `<http://services>`, the scenarios as authored to `<http://scenarios>`. The default graph is kept empty.
4. Writes what the closure **added** to a companion graph next to each closed section: `<http://inferred/ontology_dici_onto>`, `<http://inferred/classes_and_attributes>` and `<http://inferred/services>`. So the graph a user built holds exactly what they asserted (a turbine `locatedIn` its park, once), and the derived triples (`locationContains`, `linksComponent`, `a Component`, ...) sit next to it, labelled as derived.

Every write outside provisioning that replaces an asserted section (the Ontology Manager's upload, the Replica Builder's upload, an onboarding-agent edit) calls `refresh_inferred`, which recomputes the companions from the asserted graphs. A derived triple never outlives the triple it came from.

The default `rdfs-plus` profile materialises:

- `rdfs:subClassOf` transitive closure. `?inst a dici_onto:Component` catches every `WindTurbine`, `Building`, `EnergyConverter` instance without the query knowing the class hierarchy.
- `rdfs:subPropertyOf` transitive closure. `?inst dici_onto:hasAttribute ?attr` catches every typed attribute predicate (e.g. `hasBuildingGrossFloorArea`).
- `owl:equivalentClass`, `owl:equivalentProperty`, `owl:inverseOf` propagation.
- `owl:sameAs` (between distinct terms) and basic OWL property characteristics (`TransitiveProperty`, `SymmetricProperty`).

Deliberately **not** materialised: `rdfs:domain` / `rdfs:range` propagation. In OWL these are typing rules, so "domain Location" would retype whatever uses the predicate as a Location. The platform's rule is that using a link never changes what a thing is, so domain and range are kept as metadata (documentation for people and tools) and set aside during reasoning. The provisioning log says so: `[inference] N domain/range declaration(s) kept as metadata, excluded from reasoning`.

The closure runs **once per workspace open**, not per query. A one-time cost amortised over the session.

## Why materialise, instead of relying on the triplestore?

The platform supports two triplestore backends:

| Backend | Default? | Inference support |
|---|---|---|
| Apache Jena Fuseki (TDB2) | Yes (Apache-2.0) | None native |
| Ontotext GraphDB Free | Opt-in overlay | Configurable rulesets |

Materialising at write time means the same query returns the same results on either backend. Fuseki's lack of native inference becomes invisible. It also means workspace TTLs stay portable: nothing about the on-disk format is tied to a particular triplestore.

Every section lands in its **own named graph**, and queries name the graphs they read with `FROM` clauses (see `backend/graphdb/graphs.py`, `from_clause`). One switch decides whether a query sees the derived triples: `from_clause(..., inferred=True)` (the default) reads each named graph together with its companion, so `?x a dici_onto:Component` keeps working; `inferred=False` reads only what was asserted, which is what "which link did I choose?" needs (the agent's `show links` command, the contract, the Q&A links tool). `graph_union` does the same for an explicit `GRAPH` pattern. Naming the graphs explicitly sidesteps the backends' different default-graph semantics (Fuseki's default graph is only the default graph; GraphDB's is the union of all graphs), so a query returns the same rows on either. It also lets the platform replace one section (for example the ontology) without touching the others. Derived collections live in `<http://collections>` and are recomputed, not inferred.

## What this means for queries

The platform ships pre-written SPARQL with each module (Component Explorer, Data Products, etc.). If you write your own queries via the Query Manager UI, you get to lean on the materialised closure too:

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>

# Catches WindTurbine, Building, EnergyConverter, anything subClassOf* Component
SELECT ?inst
FROM <http://ontology_dici_onto>
FROM <http://classes_and_attributes>
WHERE { ?inst a dici_onto:Component }

# Catches every typed hasXAttribute predicate
SELECT ?attr
FROM <http://ontology_dici_onto>
FROM <http://classes_and_attributes>
WHERE { ?inst dici_onto:hasAttribute ?attr }
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
| Query returns rows on GraphDB, 0 on Fuseki | Query relies on GraphDB's union default graph | Name the graphs with `FROM <http://ontology_dici_onto>` / `FROM <http://classes_and_attributes>` (and `<http://services>`, `<http://scenarios>`, `<http://collections>` as needed). |
| An instance is suddenly typed as something it is not | Expecting `rdfs:domain` / `rdfs:range` to type instances | They are metadata here, never reasoning. Type the instance explicitly. |
| Query returns 0 even after inference | Predicate has no `subPropertyOf` chain to `hasAttribute` | Add the chain in your extension TTL. Fix the model, not the query. |
| Subclass inference seems missing | `subClassOf` declaration on the class is itself missing | Same. Fix the extension. |
| Provisioning takes > 10 s on a small workspace | Closure is expensive for the data shape | Lower profile to `rdfs` or `none`. |
| `[inference] stripped N non-RDF-1.1-compliant triple(s)` warning | owlrl produced literal-subject edge-case triples | Safe to ignore. They're filtered before upload. |

## A note on extending the ontology

If you find that `?x a dici_onto:SomeClass` doesn't return what you expect, the answer is almost always to **extend the ontology**, not to rewrite the query. Add a subclass (or sub-property) declaration in your workspace's `ontology/extensions/`. The Ontology Manager UI does this for you. No SPARQL required. After the next workspace open, the platform re-materialises the closure and your query just works.

For how an extension concept eventually gets promoted back into the shared `dici_onto:` core, see [`digicities-ontology/docs/CORE_EVOLUTION.md`](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/CORE_EVOLUTION.md). It covers workspace, multi-workspace adoption, core release, with promotion criteria and the service-compatibility contract.
