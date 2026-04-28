#!/usr/bin/env bash
# Configure fail2ban for SSH only.
# HTTP brute-force is handled at the Cloudflare edge (WAF + Rate Limit + Turnstile),
# so we don't try to defend HTTP through the proxy here.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "must run as root" >&2; exit 1; fi

apt-get install -y --no-install-recommends fail2ban

cat >/etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled  = true
port     = 22
filter   = sshd
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 24h
EOF

systemctl enable --now fail2ban
systemctl restart fail2ban
fail2ban-client status sshd || true
echo "[fail2ban] sshd jail active."
