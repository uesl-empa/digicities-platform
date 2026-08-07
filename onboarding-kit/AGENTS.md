# AGENTS.md — onboard this folder onto Digicities

> **This file is model-agnostic.** It is a reusable brief: drop it into *any*
> working folder that contains a model and its data, and it describes how to
> onboard that folder onto Digicities. It says nothing about a specific usecase —
> everything usecase-specific you learn by reading this folder.

You are onboarding **the model and data in this working folder** onto the
**Digicities** platform, so the user can build scenarios and submit them to the
model and get results back.

## Step 0 — get the platform running, with the right setup

Before onboarding anything, make sure the Digicities platform is set up and
running. It is configured in `.env` **before** `docker compose up` (Docker only
sees what is mounted/set at launch), so first present the user the pre-Docker
choices — the full list with explanations is in **`digicities-platform/AGENTS.md`
→ "Setup — present these options to the user before `docker compose up`"**. The
three to confirm, each with a sensible default:

1. **Do you have a workspace to load?** If the user already has workspace folder(s)
   following the template layout, set `USECASES_HOST_PATH`
   to the directory that contains them so they appear on the landing page. For
   *this* onboarding you'll create a new workspace for the model in this folder, so
   "start fresh" is usually fine.
2. **Storage backend** — local filesystem (default) or NextCloud (`STORAGE_BACKEND`).
3. **Triplestore** — Fuseki (default) or the GraphDB overlay (`TRIPLESTORE_BACKEND`).

If the user has no preference, accept the defaults (local + Fuseki + auth off) and
run `docker compose up -d --build`; confirm the app is up at http://localhost:8501
before continuing. If the user asks what any choice means, that platform setup
section explains each — use it to answer them.

## What you can assume is set up

- **This folder** contains a model plus the (probably disorganised) data it
  consumes, in the author's own formats. Nothing is in a Digicities format yet.
  The **model code is the ground truth** for what data actually matters and in
  what units — read it, and the data files, before anything else.
- A clone of the **Digicities ecosystem** (the `digicities-platform` repo) is
  available and running locally, and you've been pointed at it. Read its docs
  first, in order: `docs/GETTING_STARTED.md`, `docs/ONBOARDING_A_USECASE.md` (the
  full recipe), `docs/INTEGRATING_A_SERVICE.md`, `docs/WORKSPACE_LAYOUT.md`,
  `docs/SEMANTIC_LAYER.md`, and the repo-root `AGENTS.md` (the tool index).

## Your goal

Represent this usecase in Digicities — an extended ontology, a digital replica, a
service template, and scenarios — then wire the model up and run a scenario
through it. **How to represent it is your decision**, derived from the model and
its data. There is no prescribed answer.

## The job, as decisions — each made with a platform tool

1. **Understand the usecase.** Read the data files and the model. Work out the
   entities, how they nest/link, the attributes each carries, and their units.
2. **Create the workspace — do this early.** Everything that follows (the ontology
   extension, the replica, the scenarios, the service template) lives inside a
   Digicities **workspace**, so create/register one first. Use the landing page's
   **Create a new workspace** form, or make a folder following
   `docs/WORKSPACE_LAYOUT.md`; then make it visible to the running app (mount it
   at `/app/data/usecases` via `USECASES_HOST_PATH`, or drop it in
   `demo_workspaces/`) and open it.
3. **Check what the ontology already covers, and reuse it.** Inspect the **core
   ontology** before inventing anything — many concepts already exist. Use the
   **Ontology Manager** and **Digital Replica Explorer** to browse the existing
   component and attribute classes (or query the graph).
   **Map semantically, not by name:** every core term carries machine-readable
   annotations (`rdfs:comment`, `skos:definition`, `skos:altLabel` synonyms,
   `skos:example`, `skos:scopeNote`). Before deciding where a domain concept
   hangs (e.g. a *WindPark* → `dici_onto:Location`, whose altLabels include
   "Site"), consult the generated **term index** — vendored in the platform
   clone at `data/ontology/term-index.{json,md}`, no network needed — and follow
   the procedure in the ontology repo's **`docs/AGENT_MAPPING_GUIDE.md`**
   (<https://github.com/uesl-empa/digicities-ontology>) — or query the
   annotations via SPARQL.
4. **Decide and propose the missing vocabulary.** For what core doesn't cover,
   decide the new component types, the attribute classes (physical / categorical
   / dynamic / cost / …), the categories' allowed values, and how components link.
   Author them as this workspace's ontology extension with the **Ontology Manager**.
   Give every new term the same annotations (`rdfs:comment` at minimum; ideally
   `skos:altLabel` / `skos:example`) so the next mapping over your extension
   works too — `tools/validate_extension.py` in the ontology repo enforces this.
5. **Build the replica.** Load the actual instances with the **Replica Builder**
   (Excel import is usually fastest).
6. **Describe the payload.** Build the service requirements template with the
   **Service Requirements Builder**, mapping your ontology terms to the fields the
   model expects.
7. **Organise scenarios.** Assemble scenarios from the replica in the **Scenario
   Builder**. To generate *what-if* variants of an existing scenario (change a few
   attributes, sweep a parameter), use the **Assumptions Module** — it writes thin
   scenarios (replica references + `supersedesAttribute` overrides), same shape as
   the Scenario Builder. (Archived module: enable "Show archived modules".)
8. **Hook up and run.** Register the service endpoint and run Convert → Submit in
   **API Data Submission**. If the model consumes a live stream or wants a
   different shape, add a small transport adapter (see
   `INTEGRATING_A_SERVICE.md` step 5) and wire it into the orchestration / RDP
   pipeline. Confirm a scenario is turned into a payload and sent to the model.

## Work with the model author — confirm, don't guess

You are **not** deciding the modelling alone. Whenever something is uncertain or
consequential, **ask the model author (the user) and confirm before you commit
it**. In particular, propose your reasoning and get explicit sign-off before:

- assigning which **core class a new component or attribute hangs off** (its
  parent), or creating a **new hierarchy branch** under the core ontology;
- choosing a **kind** for an attribute (physical vs categorical vs dynamic vs …);
- fixing the **allowed values** of a categorical, or the **unit** of a quantity;
- deciding **how entities link** to each other and to the scenario.

If the data or the model is ambiguous about meaning or units, don't paper over it —
ask. Silent guesses on any of the above change what the data *means*.

## Definition of done

- The workspace opens in Digicities and its components appear in the Explorer.
- A scenario built from the replica **converts** against the service template with
  every field resolved (no unresolved `.URI` / `.label` leftovers).
- **Submit** returns the model's result.

## Report friction as you go

Onboarding is also a test of the platform. Wherever a step is unclear, a doc is
wrong or missing, a tool fights you, or the ontology/platform can't express
something the usecase needs — **write it down**. That list is a primary output.
