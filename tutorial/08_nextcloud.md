# 08 — Local NextCloud (optional)

By default the platform stores files on the local filesystem under `data/`. That's fine for scripting, but the browser-based Streamlit UI can only show files through download buttons — you can't just "open a folder" from inside a container.

If you'd rather have a real file browser — drag-and-drop uploads, previews, sharing — the stack ships with an optional NextCloud overlay. When you enable it, every TTL, every timeseries, every mapping the UI writes goes into NextCloud's WebDAV tree, which you can browse at `http://localhost:8080`.

## 1. Enable the NextCloud overlay

The NextCloud services live in a separate compose file (`docker-compose.nextcloud.yml`) so `docker compose up -d` stays fast for users who don't need them. Turn them on by telling Compose to merge that file with the others. Edit `.env` and add:

**macOS / Linux:**
```env
COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker-compose.nextcloud.yml
COMPOSE_PATH_SEPARATOR=:
NEXTCLOUD_BASIC_USERNAME=admin
NEXTCLOUD_BASIC_PASSWORD=admin
```

**Windows:**
```env
COMPOSE_FILE=docker-compose.yml;docker-compose.override.yml;docker-compose.nextcloud.yml
COMPOSE_PATH_SEPARATOR=;
NEXTCLOUD_BASIC_USERNAME=admin
NEXTCLOUD_BASIC_PASSWORD=admin
```

That's the only `.env` change needed. The overlay file itself injects `STORAGE_BACKEND=nextcloud`, `NEXTCLOUD_BASE_URL=http://nextcloud:80`, and the credentials above into the Streamlit container automatically — no manual wiring.

## 2. Bring the stack up

```bash
docker compose up -d
```

First time only, this pulls `nextcloud:29-apache` (~500 MB), starts the container, and runs a small init sidecar that creates the workspace folder skeleton over WebDAV. Initialisation inside NextCloud takes 30–90 seconds past the image download.

Check the whole stack is healthy:

```bash
docker compose ps
# should show digicities-fuseki, digicities-nextcloud, digicities-streamlit
curl -I http://localhost:8080/status.php
```

Open **http://localhost:8080** in a browser — log in with `admin` / `admin`.

## 3. Seed the tutorial workspace

With the overlay running, re-run the tutorial launcher. It detects NextCloud automatically and uploads seed content on top of the GraphDB data load:

```bash
python tutorial/start_tutorial.py
```

Output includes a NextCloud section like:

```
[tutorial] seeding NextCloud workspace 'workspace_demo' as user 'admin'
[tutorial]    ontology ext  [201]  alpine_village_extension.ttl
[tutorial]    data product  alpine_village_map: 2 file(s)
[tutorial]    data product  building_a_electricity_demand: 2 file(s)
[tutorial]    data product  pv_a_generation: 2 file(s)
```

After this step the workspace contains:

| NextCloud path | What it is | Where it shows up in Streamlit |
|---|---|---|
| `/workspace_demo/ontology/extensions/alpine_village_extension.ttl` | 5 alpine-specific classes + 1 property on top of `dici_onto_core` | **Ontology Manager** → load this extension to see the classes |
| `/workspace_demo/private_data_products/building_a_electricity_demand/` | 168 h of hourly demand CSV + manifest | **Data Products** → renders as a line chart |
| `/workspace_demo/private_data_products/pv_a_generation/` | 168 h of PV generation CSV + manifest | **Data Products** → compare against demand |
| `/workspace_demo/private_data_products/alpine_village_map/` | 7-point GeoJSON of component locations | **Data Products** → opens in the Folium map renderer |

The seed is idempotent — re-running `start_tutorial.py` safely overwrites existing files. If you want to skip just the seed step (for instance because you're testing something else), pass `--no-nextcloud`.

## 4. Verify in the UI

Open Streamlit at http://localhost:8501 and expand **📊 System Status** in the left sidebar.

- **💾 Storage** should now show `Backend: nextcloud` and a clickable link to `http://localhost:8080/`.
- **🧩 Optional services** should show `NextCloud storage: ✅ configured` with a browse link.
- The **Data Viewer and Uploader** module in the main area is no longer greyed out.

Upload a file through the UI, then switch to http://localhost:8080 and navigate to **Files → workspace_demo/** — the file is right there.

## Credentials — what you need to know

The `admin` / `admin` pair you see in `.env.example` and `docker-compose.yml` are **local-stack defaults**, not secrets. They only protect NextCloud on `localhost`, so an attacker would need filesystem-level access to your machine to even see the port.

**Don't ship them past localhost.** If you publish this compose to a VPS, a shared network, or a cloud VM, at minimum:

1. Change `NEXTCLOUD_BASIC_USERNAME` / `NEXTCLOUD_BASIC_PASSWORD` in `.env` to something strong.
2. Remove the `ports: "8080:80"` exposure (put NextCloud behind a reverse proxy with TLS).

The Keycloak story is out of scope for this tutorial — see the production deployment docs.

## Where files actually live

The NextCloud container persists to a Docker named volume (`nextcloud_data`). That survives container restarts but is opaque from your host filesystem — which is exactly what you were complaining about with the generic Docker-only storage. The difference is that now you can see and manage files through NextCloud's UI.

If you want the data on your host filesystem directly, edit `docker-compose.nextcloud.yml`:

```yaml
  nextcloud:
    volumes:
      - ./data/nextcloud:/var/www/html   # bind mount instead of named volume
```

and `docker compose up -d --force-recreate nextcloud` again. `./data/nextcloud/` on your host will then mirror the container's state.

## Troubleshooting

**`init` container exits with `ERROR: WebDAV never returned 200`.**
NextCloud's `/status.php` comes up before user setup finishes, but the init script keeps polling — so this only fires if setup genuinely fails. Usually the trusted-domains list is wrong: from the sibling Streamlit/init container the Host header is `nextcloud`, which must be listed. Check:

```bash
docker exec -u www-data digicities-nextcloud php occ config:system:get trusted_domains
```

You should see `localhost`, `nextcloud`, and `digicities-nextcloud`. If `nextcloud` is missing (e.g. you upgraded from an older compose), add it:

```bash
docker exec -u www-data digicities-nextcloud \
  php occ config:system:set trusted_domains 1 --value=nextcloud
docker compose --profile nextcloud up -d --force-recreate nextcloud-init
```

**Data Viewer module still says "Nextcloud not configured" after switching `.env`.**
Streamlit only reads env at container start, and adding `COMPOSE_FILE` to `.env` changes how Docker Compose *constructs* the project — so a simple restart isn't enough. Force a recreate so the Streamlit container picks up the NextCloud env the overlay injects:

```bash
docker compose up -d --force-recreate streamlit
```

Confirm the env is live:

```bash
docker exec digicities-streamlit printenv | grep NEXTCLOUD
```

You should see `NEXTCLOUD_BASE_URL`, `NEXTCLOUD_BASIC_USERNAME`, `NEXTCLOUD_BASIC_PASSWORD`, and `STORAGE_BACKEND=nextcloud`.

**The UI at `http://localhost:8080` shows "Access through untrusted domain".**
You hit the NextCloud UI on a hostname that isn't in `trusted_domains`. Same fix as above — add the hostname via `occ config:system:set trusted_domains`.

## Tearing it down

```bash
docker compose --profile nextcloud down         # stop containers, keep data
docker compose --profile nextcloud down -v      # stop + delete nextcloud_data volume
```

`-v` removes the volume, which wipes everything you uploaded. You're back to a clean NextCloud next time you bring the profile up.
