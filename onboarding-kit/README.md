# Digicities onboarding kit

A tiny, **model-agnostic** kit for onboarding an existing model + its data onto
Digicities with an agent. It is two files — [`AGENTS.md`](AGENTS.md) (the agent's
brief) and this README — that you drop into a **working folder** (a folder holding
a model and the data it consumes). Nothing in the kit is specific to any usecase.

## The pipeline

1. **Copy the kit into your working folder.** Copy `AGENTS.md` (and this README)
   from here into the folder that contains your model + data.
2. **Clone and run the Digicities ecosystem.** Clone the `digicities-platform`
   repo next to it and bring it up:
   ```bash
   cp .env.example .env && docker compose up -d   # Fuseki :3030 + Streamlit :8501
   ```
3. **Point your agent at both** — the Digicities ecosystem and your working
   folder. It reads `AGENTS.md` and drives the onboarding.

In theory any working folder can be onboarded this way: the kit carries the
process, the working folder carries the usecase, and the ecosystem carries the
tools.

## What the agent will do

Turn your model + data into a Digicities workspace: inspect the core ontology and
reuse what fits; propose and author the missing components/attributes/links;
build the digital replica; write the service template; assemble scenarios; then
register the service and submit a scenario to it. It uses the platform's own
modules for each step (Ontology Manager, Replica Builder, Service Requirements
Builder, Scenario Builder, API Data Submission). Full recipe:
`digicities-platform/docs/ONBOARDING_A_USECASE.md`.

## Your part (human in the loop)

The agent will **ask you to confirm the consequential modelling decisions** — for
example where a new class sits under the core ontology, whether an attribute is
categorical or physical, a unit, or how two entities link. Expect questions about
what your model's inputs *mean* and their units; the model is the source of truth
and you know it best.

## Prerequisites

- Docker Desktop, to run the Digicities stack.
- Your working folder's model runnable enough that you can describe its inputs
  (the agent reads the code, but you resolve ambiguities).
