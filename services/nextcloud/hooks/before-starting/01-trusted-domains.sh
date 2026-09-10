#!/bin/sh
# Re-assert trusted_domains on EVERY container start.
#
# NEXTCLOUD_TRUSTED_DOMAINS is only read by the image on FIRST boot (written
# into config.php and ignored thereafter) — the classic gotcha: rename a
# service or add a public hostname, and sibling containers start getting the
# login page with HTTP 400 because their Host header isn't trusted. This
# before-starting hook makes the env var authoritative on every start instead.
#
# Runs inside the official image's entrypoint (as www-data), where occ is
# available. Before the very first installation config.php doesn't exist yet
# and occ refuses to run — skip silently; the env var covers first boot.

set -eu

if ! php occ status --no-warnings >/dev/null 2>&1; then
    echo "trusted-domains hook: NextCloud not installed yet — skipping (first-boot env applies)."
    exit 0
fi

i=0
for domain in ${NEXTCLOUD_TRUSTED_DOMAINS:-localhost}; do
    php occ config:system:set trusted_domains "$i" --value="$domain" --no-warnings >/dev/null
    i=$((i + 1))
done
echo "trusted-domains hook: set ${i} trusted domain(s): ${NEXTCLOUD_TRUSTED_DOMAINS:-localhost}"
