#!/usr/bin/env bash
# Issue / renew a Let's Encrypt cert for $DOMAIN via DNS-01 against Cloudflare.
# Uses certbot with the dns-cloudflare plugin in a one-shot Docker container,
# so nothing extra is installed on the host.
#
# Requires in .env: DOMAIN, LE_EMAIL, CLOUDFLARE_API_TOKEN
# Token scope: Zone:Zone:Read + Zone:DNS:Edit, restricted to this zone only.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

: "${DOMAIN:?DOMAIN not set}"
: "${LE_EMAIL:?LE_EMAIL not set}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN not set}"

CERTS_DIR="$(pwd)/nginx/certs"
LE_DIR="$(pwd)/nginx/letsencrypt"
mkdir -p "$CERTS_DIR" "$LE_DIR"

CRED_FILE="$LE_DIR/cloudflare.ini"
install -m 0400 /dev/null "$CRED_FILE"
printf 'dns_cloudflare_api_token = %s\n' "$CLOUDFLARE_API_TOKEN" >"$CRED_FILE"

echo "[cert] running certbot for $DOMAIN"
docker run --rm \
  -v "$LE_DIR:/etc/letsencrypt" \
  -v "$CRED_FILE:/cloudflare.ini:ro" \
  certbot/dns-cloudflare:v2.11.0 \
  certonly \
    --non-interactive --agree-tos \
    --email "$LE_EMAIL" \
    --dns-cloudflare \
    --dns-cloudflare-credentials /cloudflare.ini \
    --dns-cloudflare-propagation-seconds 30 \
    -d "$DOMAIN"

LIVE="$LE_DIR/live/$DOMAIN"
install -m 0644 "$LIVE/fullchain.pem" "$CERTS_DIR/fullchain.pem"
install -m 0640 "$LIVE/privkey.pem"   "$CERTS_DIR/privkey.pem"

# Wipe creds file once we're done — token doesn't need to linger
shred -u "$CRED_FILE" 2>/dev/null || rm -f "$CRED_FILE"

if docker compose ps nginx --status running >/dev/null 2>&1; then
  docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload
fi

echo "[cert] cert installed at $CERTS_DIR/fullchain.pem (renewals: re-run this script)"
