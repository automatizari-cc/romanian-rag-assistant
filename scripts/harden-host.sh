#!/usr/bin/env bash
# One-shot host hardening for a fresh Hetzner CX53 (Debian/Ubuntu).
# Idempotent. Run as root.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "must run as root" >&2; exit 1
fi

echo "[harden] apt update + base tools"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg ufw fail2ban unattended-upgrades \
    apt-listchanges cron jq

echo "[harden] enable unattended-upgrades"
dpkg-reconfigure -f noninteractive unattended-upgrades
systemctl enable --now unattended-upgrades

echo "[harden] disable IPv6 (sysctl)"
cat >/etc/sysctl.d/99-disable-ipv6.conf <<'EOF'
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
sysctl --system >/dev/null

echo "[harden] disable IPv6 in Docker daemon"
mkdir -p /etc/docker
if [[ -f /etc/docker/daemon.json ]]; then
  tmp="$(mktemp)"
  jq '. + {ipv6:false, "log-driver":"json-file", "log-opts":{"max-size":"10m","max-file":"3"}}' \
     /etc/docker/daemon.json >"$tmp"
  mv "$tmp" /etc/docker/daemon.json
else
  cat >/etc/docker/daemon.json <<'EOF'
{
  "ipv6": false,
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
fi
systemctl restart docker || true

echo "[harden] SSH: key-only, no root password login"
sshd_cfg=/etc/ssh/sshd_config.d/99-hardening.conf
cat >"$sshd_cfg" <<'EOF'
PasswordAuthentication no
PermitRootLogin prohibit-password
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
chmod 644 "$sshd_cfg"
sshd -t
systemctl reload ssh || systemctl reload sshd

echo "[harden] done. Reboot recommended to fully drop IPv6 from the kernel."
