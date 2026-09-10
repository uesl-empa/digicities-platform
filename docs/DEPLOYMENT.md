# Deploying Digicities

Two deployment tiers, one codebase:

| Tier | Storage | Who can reach the files | Compose |
|---|---|---|---|
| **Local (Docker Desktop)** — clone & run | local filesystem (default, unchanged) | you, in the workspace folder on disk | `docker compose up -d` |
| **Cloud / server + web app** | server-local working copy **mirrored to NextCloud** | users, through NextCloud's web UI + the app's download/upload features | `docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d` |

The cloud tier exists because a browser cannot reach the server's filesystem:
NextCloud is the user-facing durable store, while the containers keep a local
working copy (the converter and the onboarding agent need real files). A
mirror layer (`backend/workspace/mirror.py`) syncs the two — pull on every
workspace read (throttled), push after every write — and is a hard no-op on
the local tier, which is why nothing changes for cloned-repo users.

## Cloud deployment

### 1. Configure `.env`

The deploy overlay **refuses to start** without real credentials — there are
no admin/admin defaults on this path.

```bash
# REQUIRED by docker-compose.deploy.yml
NEXTCLOUD_BASIC_USERNAME=admin
NEXTCLOUD_BASIC_PASSWORD=<strong password>       # NextCloud admin + platform's WebDAV login
NEXTCLOUD_DB_PASSWORD=<strong password>          # NextCloud's own Postgres

# Recommended
NEXTCLOUD_PUBLIC_HOST=files.your-domain.example  # extra trusted domain for browser traffic
NEXTCLOUD_PORT=8080                              # host port for the NextCloud web UI
CORS_ORIGINS=https://app.your-domain.example     # lock the API to the frontend origin
REQUIRE_LOGIN=1                                  # plus JWT_SECRET / ADMIN_* (see README)
```

To use a **managed/external NextCloud** instead of the bundled one: skip the
overlay's nextcloud services and set `STORAGE_BACKEND=nextcloud`,
`NEXTCLOUD_BASE_URL`, and the credentials on the `api` and `streamlit`
services yourself — the code path is identical.

### 2. Verify locally BEFORE deploying

The whole cloud storage stack runs on Docker Desktop, so validate it before
anything leaves your machine:

```bash
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d
# wait for healthchecks; nextcloud-init seeds the canonical layout

NEXTCLOUD_LIVE_URL=http://localhost:8080 \
NEXTCLOUD_LIVE_USER=admin NEXTCLOUD_LIVE_PASSWORD=<your pw> \
    pytest -m live tests/test_nextcloud_live.py -v
```

(PowerShell: set the three `$env:NEXTCLOUD_LIVE_*` variables, then run the
pytest line.) The suite exercises the real WebDAV op surface, the full mirror
cycle (push, pull, remote-edit pickup, deletion propagation, secrets
exclusion), workspace autodiscovery, and the pull throttle — in a throwaway
`workspace_livecheck` folder it creates and removes itself.

Then click around: create a workspace in the app, onboard something, and
watch the files appear at `http://localhost:8080`.

### 3. Deploy

Same compose command on the server. The overlay ships its own reverse proxy /
TLS terminator (the `proxy` service, below) — the only ports open to the
internet are 80/443; everything else is rebound to `127.0.0.1` (reach it via
SSH tunnel when needed).
Add your public hostname to `NEXTCLOUD_PUBLIC_HOST` — trusted domains are
re-asserted from the env on **every** container start (a before-starting
`occ` hook), so changing them later is an `.env` edit + restart, not a
config.php surgery.

### 4. Verify AFTER deploying

The **same suite**, pointed at the deployed instance — plus the optional
end-to-end API check:

```bash
NEXTCLOUD_LIVE_URL=https://files.your-domain.example \
NEXTCLOUD_LIVE_USER=... NEXTCLOUD_LIVE_PASSWORD=... \
DIGICITIES_API_URL=https://api.your-domain.example \
    pytest -m live tests/test_nextcloud_live.py -v
```

With `DIGICITIES_API_URL` set, the last test drives the REST stack end to
end: the throwaway workspace must be autodiscovered from NextCloud and its
files listing served through `get_ctx → mirror.pull → ws_root`.

## Private multi-user deployment (password-protected site)

The platform has built-in accounts (email + password, bcrypt-hashed, JWT
sessions) stored in the metadata Postgres, with per-workspace access
control: each workspace has an owner, `private`/`shared` visibility, and an
editor list. To run a closed instance where you hand out accounts and each
project's members see only that project's workspaces:

**1. Env** (see the "Private multi-user deployment" block in `.env.example`):
`REQUIRE_LOGIN=1`, `ALLOW_REGISTRATION=0`, a real `JWT_SECRET`,
`ADMIN_EMAIL`/`ADMIN_PASSWORD` (the first admin, seeded on api startup),
`FRONTEND_DIR` (a `digicities-frontend` checkout — the `proxy` service builds
its Dockerfile), and `DOMAIN` for automatic HTTPS.

**2. Public surface**: only the `proxy` service (Caddy) is exposed — it
serves the built React app and proxies `/api` to the api container. Streamlit
(which runs authless under `AUTH_DISABLED`), Fuseki, Postgres, and NextCloud
are loopback-only. Do NOT open them: Streamlit and Fuseki would bypass the
login wall entirely.

**3. Create the accounts** (admin token from `POST /api/auth/login`):

```bash
TOKEN=$(curl -s -X POST https://$DOMAIN/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.org","password":"..."}' | jq -r .token)

curl -X POST https://$DOMAIN/api/auth/users -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"email":"member@project.org","password":"...","display_name":"Member"}'
```

(`GET /api/auth/users` lists accounts; `DELETE /api/auth/users/{email}`
removes one plus its grants. `is_admin: true` on create makes another admin —
admins see and manage **every** workspace.)

**4. Assign each project's workspaces** — one declarative call per workspace
sets owner, makes it private, and fixes the member list (grants *and*
revokes):

```bash
curl -X POST https://$DOMAIN/api/workspaces/<workspace_id>/assign \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"owner_email":"lead@project.org","visibility":"private",
       "members":["member@project.org","other@project.org"]}'
```

A private workspace is invisible (404, not 403) to everyone but its owner,
members, and admins. Workspaces never assigned stay `shared` — visible to
every signed-in account — so assign everything that belongs to a project.

**5. Frontend behaviour**: signed-out visitors get the sign-in gate; the
Register tab hides itself when `ALLOW_REGISTRATION=0` (via
`GET /api/auth/config`). Owners can also grant one-off access in-app via
`POST /api/workspaces/{id}/share`.

## What users get on the cloud tier

- Workspace file browse/download/upload through the app (and the agent's
  `files` / `download` chat commands). NextCloud's own web UI is
  loopback-only by default — it has a single admin login (the platform's
  WebDAV credential), so exposing it would hand every visitor all projects'
  files. Set `NEXTCLOUD_BIND=0.0.0.0` only for a single-team instance where
  that's acceptable.
- **Edit-in-NextCloud workflow** (when you expose it, or via SSH tunnel):
  open the ingestion workbook in NextCloud Office, fix values, save — the
  agent's next read (`template`, resubmit, `files`) picks the edit up through
  the mirror pull. No re-upload needed.
- Durability: workspaces live in NextCloud; the server's working copy is a
  cache. A redeployed api container re-pulls everything on first access, and
  NextCloud-side workspaces are autodiscovered (any folder carrying
  `workspace_meta/metadata.json`).

## Sync semantics (what the mirror guarantees)

- A **pull never deletes** local work that hasn't been pushed.
- A **push never deletes** a remote file the mirror hasn't seen — files users
  create directly in NextCloud are safe.
- `reset workspace` in the agent chat propagates its wipe to NextCloud.
- Secrets (`.agent-keys.json`) and the sync manifest never leave the server.
- Storage hiccups are logged, never turned into HTTP 500s.
- v1 concurrency: one api instance, last-writer-wins.

Three permanent tests keep this true for future code:
`test_storage_parity_gate.py` (no new ad-hoc path derivations),
`test_storage_parity.py` (op-surface parity across backends, every run), and
`test_nextcloud_live.py` (the real thing, in the `nextcloud-live` CI workflow
and in the pre-/post-deploy procedure above).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| MKCOL / WebDAV returns 400 with correct creds | Host header not in trusted domains. Add it to `NEXTCLOUD_TRUSTED_DOMAINS` / `NEXTCLOUD_PUBLIC_HOST` and restart — the hook re-applies on start. |
| compose fails with `set NEXTCLOUD_… in .env` | Intentional: the deploy overlay requires real credentials. |
| Files edited in NextCloud not visible in the app | Within the pull throttle window (`MIRROR_PULL_SECONDS`, default 30s) — wait or lower it. |
| Deleted workspace reappears | Fixed in the mirror arc (`delete_workspace` clears remote + local + discovery cache); if seen, check you're on a build that includes it. |
