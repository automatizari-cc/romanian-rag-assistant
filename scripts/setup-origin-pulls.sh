#!/usr/bin/env bash
# Install Cloudflare's Origin Pull CA so nginx can mTLS-verify that every
# request reaching the VM came through Cloudflare.
#
# Reference: https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/
#
# After running this, enable "Authenticated Origin Pulls" in the Cloudflare
# dashboard for this zone (SSL/TLS -> Origin Server -> Authenticated Origin Pulls).
set -euo pipefail
cd "$(dirname "$0")/.."

CA_URL="https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem"
DEST="nginx/cf-origin-pull-ca.pem"

echo "[aop] downloading Cloudflare origin-pull CA"
curl -fsS "$CA_URL" -o "$DEST.tmp"

# Sanity check: must be a PEM with at least one CERTIFICATE block
if ! grep -q "BEGIN CERTIFICATE" "$DEST.tmp"; then
  echo "[aop] downloaded file is not a PEM cert; aborting" >&2
  rm -f "$DEST.tmp"
  exit 1
fi
mv "$DEST.tmp" "$DEST"
chmod 0644 "$DEST"

if docker compose ps nginx --status running >/dev/null 2>&1; then
  docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload
fi

echo "[aop] CA installed at $DEST"
echo "[aop] remember to ENABLE 'Authenticated Origin Pulls' in Cloudflare dashboard"
