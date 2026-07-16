#!/bin/sh
# GraphDB initialisation — runs once after GraphDB is healthy.
# Creates the 'workspace_demo' repository and loads the core ontology
# into the named graph <http://ontology_dici_onto>.

set -e

GRAPHDB_URL="http://graphdb:7200"
REPO="workspace_demo"
ONTOLOGY_GRAPH="http://ontology_dici_onto"

echo "==> Checking if repository '${REPO}' already exists..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${GRAPHDB_URL}/rest/repositories/${REPO}")

if [ "$STATUS" = "200" ]; then
  echo "==> Repository '${REPO}' already exists. Skipping creation."
else
  echo "==> Creating repository '${REPO}'..."
  HTTP=$(curl -s -o /tmp/create_out.txt -w "%{http_code}" \
    -X POST "${GRAPHDB_URL}/rest/repositories" \
    -H "Content-Type: multipart/form-data" \
    -F "config=@/init/repo-config.ttl;type=text/turtle")
  echo "==> Create response (HTTP ${HTTP}): $(cat /tmp/create_out.txt)"

  echo "==> Waiting for repository to become available..."
  RETRIES=15
  while [ $RETRIES -gt 0 ]; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${GRAPHDB_URL}/rest/repositories/${REPO}")
    [ "$STATUS" = "200" ] && echo "==> Repository ready." && break
    RETRIES=$((RETRIES - 1))
    sleep 2
  done

  if [ "$STATUS" != "200" ]; then
    echo "==> ERROR: Repository '${REPO}' not available after waiting. Exiting."
    exit 1
  fi
fi

echo "==> Loading core ontology into <${ONTOLOGY_GRAPH}>..."
HTTP=$(curl -s -o /tmp/upload_out.txt -w "%{http_code}" \
  -X PUT \
  "${GRAPHDB_URL}/repositories/${REPO}/rdf-graphs/service?graph=${ONTOLOGY_GRAPH}" \
  -H "Content-Type: text/turtle" \
  --data-binary "@/init/ontology/dici_onto_core.ttl")

if [ "$HTTP" = "204" ] || [ "$HTTP" = "200" ]; then
  echo "==> Core ontology loaded successfully (HTTP ${HTTP})."
else
  echo "==> Warning: ontology load returned HTTP ${HTTP}: $(cat /tmp/upload_out.txt)"
fi

echo "==> GraphDB initialisation complete."
