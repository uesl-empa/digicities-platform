# External modules

This folder is the default mount point for **external UI modules** — nav entries
that live in their own repos and are loaded into the running platform, without
shipping with it.

Two ways to load a module:

1. **Drop it here**: clone a module repo into this folder
   (`git clone <module-repo> modules/<name>`) and restart
   (`docker compose up -d`). Everything in here except this README is
   git-ignored.
2. **Point at it**: set `MODULES_HOST_PATH=<path>` in `.env` — either a module
   repo itself or a folder containing several — and restart.

A module is any folder with a `module.yaml` manifest next to a Python package.
The contract (manifest fields, entry-function signature, dependency handling) is
documented in [`docs/EXTERNAL_MODULES.md`](../docs/EXTERNAL_MODULES.md).

Known modules:

| Module | Repo |
|---|---|
| Onboarding Agent — populate the active workspace from a model+data working folder, and ask its graph in plain language | [`digicities-onboarding-agent`](https://github.com/uesl-empa/digicities-onboarding-agent) |
