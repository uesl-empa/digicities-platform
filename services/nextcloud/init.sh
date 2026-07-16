#!/bin/sh
# NextCloud initialisation — runs once after the server reports healthy.
# Creates the workspace folder skeleton the Streamlit modules expect, via
# WebDAV MKCOL. Safe to re-run (existing folders return 405 which we ignore).

set -e

: "${NEXTCLOUD_URL:=http://nextcloud:80}"
: "${NEXTCLOUD_USER:=admin}"
: "${NEXTCLOUD_PASS:=admin}"
: "${WORKSPACE_ID:=workspace_demo}"

DAV_BASE="${NEXTCLOUD_URL}/remote.php/dav/files/${NEXTCLOUD_USER}"

echo "==> Seeding NextCloud workspace '${WORKSPACE_ID}' at ${DAV_BASE}"

# /status.php returning 200 doesn't mean the admin user's WebDAV root is
# reachable yet — on first boot the image needs a bit longer to finish user
# setup. Poll the admin files endpoint until we get 200 (authenticated),
# or give up after ~2 minutes.
echo "==> Waiting for WebDAV to accept authenticated requests…"
RETRIES=40
while [ "$RETRIES" -gt 0 ]; do
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    -u "${NEXTCLOUD_USER}:${NEXTCLOUD_PASS}" \
    "${DAV_BASE}/")
  if [ "$code" = "200" ]; then
    echo "   WebDAV ready (HTTP 200)."
    break
  fi
  echo "   still waiting (HTTP ${code})…"
  RETRIES=$((RETRIES - 1))
  sleep 3
done
if [ "$RETRIES" = "0" ]; then
  echo "==> ERROR: WebDAV never returned 200. Last status: ${code}"
  echo "    Check NEXTCLOUD_TRUSTED_DOMAINS includes 'nextcloud'."
  exit 1
fi

mkcol() {
  path="$1"
  # NextCloud's WebDAV requires a trailing slash on collection paths,
  # otherwise MKCOL returns HTTP 400.
  url="${DAV_BASE}/${path}/"
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    -u "${NEXTCLOUD_USER}:${NEXTCLOUD_PASS}" \
    -X MKCOL "${url}")
  case "${code}" in
    201) echo "   created  ${path}" ;;
    405) echo "   exists   ${path}" ;;
    *)   echo "   WARN[${code}]  ${path}" ;;
  esac
}

# Top-level workspace
mkcol "${WORKSPACE_ID}"

# Ontology Manager layout
mkcol "${WORKSPACE_ID}/ontology"
mkcol "${WORKSPACE_ID}/ontology/extensions"
mkcol "${WORKSPACE_ID}/ontology/exports"
mkcol "${WORKSPACE_ID}/ontology/temp"
mkcol "${WORKSPACE_ID}/ontology/mappings"
mkcol "${WORKSPACE_ID}/ontology/mappings/input"
mkcol "${WORKSPACE_ID}/ontology/mappings/output"

# Workspace-level folders used by other modules. Names must match what the
# Streamlit code looks for — see apps/streamlit/components/data_products/
# data_loader.py for the private_data_products path.
mkcol "${WORKSPACE_ID}/private_data_products"
mkcol "${WORKSPACE_ID}/scenarios"
mkcol "${WORKSPACE_ID}/services"
mkcol "${WORKSPACE_ID}/timeseries"
mkcol "${WORKSPACE_ID}/workspace_meta"

# Global folder (shared, read-only from the workspace user's perspective —
# but since this is a single-admin local NextCloud, the same user owns it).
mkcol "global"
mkcol "global/open_data_products"
mkcol "global/workspace_meta"

echo "==> NextCloud initialisation complete."
echo "==> Open the web UI at http://localhost:8080 (user: ${NEXTCLOUD_USER})"
