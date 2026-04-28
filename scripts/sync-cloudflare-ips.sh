#!/usr/bin/env bash
# Refresh the Cloudflare IPv4 ranges in:
#   1. nginx/conf.d/cloudflare-realip.conf  (set_real_ip_from list)
#   2. (optional) Hetzner Cloud Firewall rule for ports 80/443
#
# Schedule via cron, e.g.:
#   0 4 * * * /opt/romanian-rag-assistant/scripts/sync-cloudflare-ips.sh
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

CONF=nginx/conf.d/cloudflare-realip.conf
TMP="$(mktemp)"

{
  echo "# Cloudflare IPv4 ranges — refreshed by scripts/sync-cloudflare-ips.sh"
  echo "# Source: https://www.cloudflare.com/ips-v4"
  echo "# This file is regenerated; do not hand-edit."
  echo
  curl -fsS https://www.cloudflare.com/ips-v4 \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$' \
    | awk '{printf "set_real_ip_from %s;\n", $1}'
  echo
  echo "real_ip_header CF-Connecting-IP;"
  echo "real_ip_recursive on;"
} >"$TMP"

if ! cmp -s "$TMP" "$CONF"; then
  mv "$TMP" "$CONF"
  echo "[cf-sync] $CONF updated"
  if docker compose ps nginx --status running >/dev/null 2>&1; then
    docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload
  fi
else
  rm -f "$TMP"
  echo "[cf-sync] no changes"
fi

# ─── Optional: update Hetzner Cloud Firewall ────────────────────────────────
# Requires HCLOUD_TOKEN (read+write firewalls) and HCLOUD_FIREWALL_ID in .env.
if [[ -n "${HCLOUD_TOKEN:-}" && -n "${HCLOUD_FIREWALL_ID:-}" ]]; then
  command -v hcloud >/dev/null || { echo "hcloud CLI not installed; skipping FW sync"; exit 0; }
  CIDRS=$(curl -fsS https://www.cloudflare.com/ips-v4 | grep -E '^[0-9].*/[0-9]+$' | paste -sd, -)
  HCLOUD_TOKEN="$HCLOUD_TOKEN" hcloud firewall replace-rules "$HCLOUD_FIREWALL_ID" \
    --rules-file <(jq -n --arg cidrs "$CIDRS" '
      ($cidrs | split(",")) as $cf
      | [
          {direction:"in", protocol:"tcp", port:"22",     source_ips:["0.0.0.0/0"]},
          {direction:"in", protocol:"tcp", port:"80",     source_ips:$cf},
          {direction:"in", protocol:"tcp", port:"443",    source_ips:$cf}
        ]')
  echo "[cf-sync] Hetzner firewall $HCLOUD_FIREWALL_ID updated"
fi
