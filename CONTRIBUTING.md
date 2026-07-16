# Contributing to Digicities

Thanks for your interest in contributing. Digicities is young as an open-source project. Contributions of any size are welcome.

## Getting set up

```bash
git clone https://github.com/uesl-empa/digicities-platform.git
cd digicities-platform
cp .env.example .env
docker compose up -d
```

Verify the stack is healthy:

```bash
curl -I http://localhost:8501                         # HTTP/1.1 200
curl http://localhost:3030/$/ping                     # Fuseki: 'pong' (GraphDB overlay: :7201)
```

If you plan to edit Python, also install the project locally:

```bash
conda create -n digicities python=3.11 && conda activate digicities
pip install -r requirements.txt
pip install -e .
```

### Working with notebooks

The tutorial notebooks under `tutorial/` are tracked **without** cell outputs or execution metadata. Running them shouldn't produce a noisy diff. We enforce this with [`nbstripout`](https://github.com/kynan/nbstripout) via a git filter declared in `.gitattributes`. Install it once after cloning:

```bash
pip install nbstripout
nbstripout --install
```

That's it. `git add` on any `.ipynb` will now strip outputs and execution counts before staging. If you ever want to share a fully-executed notebook (for a bug report, say), pass it as a file directly rather than committing it.

## Repository layout

The layout is documented in [`AGENTS.md`](AGENTS.md) (the repo map). The two things worth internalising before you start:

- **`backend/` is the source of truth** for logic. Pure Python, no Streamlit imports. Add new functionality here first.
- **`apps/streamlit/components/` is the UI.** Thin shells that import from `backend/` and add session-state and widgets. Don't put logic here that isn't obviously UI-only.

If you're adding a feature and it doesn't need `st.*` to work, it belongs in `backend/`.

## Smoke-testing a change

We don't have a dedicated test suite yet. The tutorial notebooks are the de-facto regression tests. They exercise the full stack end-to-end against the Docker services.

Before opening a PR:

```bash
# 1. Stack is up
docker compose up -d

# 2. Full import + app load works
docker exec digicities-streamlit python -c "import apps.streamlit.app"
curl -I http://localhost:8501      # HTTP/1.1 200

# 3. All tutorial notebooks run end-to-end
cd tutorial
for nb in 01_*.ipynb 02_*.ipynb 03_*.ipynb 04_*.ipynb 05_*.ipynb 06_*.ipynb; do
  jupyter nbconvert --to notebook --execute "$nb" --output /tmp/executed.ipynb
done
```

If you changed something in `backend/graphdb/`, also re-run Alpine Village's upload/query path from notebook 01. If you changed an assumption engine, re-run notebook 04.

## Commit and PR conventions

- **One logical change per PR.** Smaller is better. If you find yourself touching twenty files, consider splitting.
- **Commit messages**: imperative mood (`add ...`, `fix ...`, `remove ...`), with a body explaining *why* if it isn't obvious.
- **Don't amend commits that have been pushed.** Create a new commit instead.
- **Don't commit `.env` (or any local `*.env`), `data/namespaces/`, `__pycache__/`.** They're gitignored, but double-check with `git status` before pushing.
- **Don't re-introduce hardcoded credentials or production URLs.** Every external endpoint should be an env var with no default pointing at a real deployment.

## What's in scope for contributions

Likely to merge quickly:

- Bug fixes in `backend/` (the `TTLParser`'s over-eager attribute detection is a known one. See the note in `tutorial/05_data_products.ipynb`).
- Documentation fixes in the tutorial notebooks.
- New adapters under `backend/api_submission/` for other optimisation APIs.
- Ontology extensions authored in a workspace's `ontology/extensions/` (or upstreamed to the [`digicities-ontology`](https://github.com/uesl-empa/digicities-ontology) repo if reusable).

Discuss first:

- Large refactors of `apps/streamlit/components/`.
- Changes to the ontology schema.
- New top-level directories or packaging changes.

## Reporting bugs

Open an issue with:

- What you were trying to do.
- What happened instead.
- The command you ran (and the `DEBUG [GraphDB]:` log lines if it's a query failure. The backend client prints them to stdout.)
- Your `.env` with any secrets redacted.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE), the same license as the rest of the project. Apache 2.0 includes an explicit patent grant from contributors to users, which is one of the main reasons the project picked it over MIT.
