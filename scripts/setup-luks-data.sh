#!/usr/bin/env bash
# Create a LUKS-encrypted /data partition from an attached block device,
# format ext4, mount at /data, and persist with a keyfile so the system
# unlocks it automatically at boot. Run as root.
#
# Usage: DATA_DEV=/dev/sdb scripts/setup-luks-data.sh
#
# WARNING: this WIPES $DATA_DEV. Confirm the device before running.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "must run as root" >&2; exit 1; fi
: "${DATA_DEV:?set DATA_DEV (e.g. /dev/sdb) — script will wipe this device}"

if [[ ! -b "$DATA_DEV" ]]; then
  echo "$DATA_DEV is not a block device" >&2; exit 1
fi

echo "[luks] About to wipe $DATA_DEV. Type the device path again to confirm:"
read -r confirm
[[ "$confirm" == "$DATA_DEV" ]] || { echo "aborted"; exit 1; }

apt-get install -y --no-install-recommends cryptsetup

KEYFILE=/root/data-luks.key
MAPPER=data_crypt
MOUNTPT=/data

if [[ ! -f "$KEYFILE" ]]; then
  echo "[luks] generating keyfile at $KEYFILE (root-only)"
  install -m 0400 /dev/null "$KEYFILE"
  dd if=/dev/urandom of="$KEYFILE" bs=4096 count=1 status=none
fi

echo "[luks] formatting $DATA_DEV"
cryptsetup luksFormat --type luks2 --batch-mode --key-file "$KEYFILE" "$DATA_DEV"
cryptsetup open --key-file "$KEYFILE" "$DATA_DEV" "$MAPPER"

echo "[luks] mkfs.ext4 on /dev/mapper/$MAPPER"
mkfs.ext4 -L data "/dev/mapper/$MAPPER"

mkdir -p "$MOUNTPT"
mount "/dev/mapper/$MAPPER" "$MOUNTPT"

UUID=$(blkid -s UUID -o value "$DATA_DEV")
grep -q "^$MAPPER " /etc/crypttab || \
  echo "$MAPPER UUID=$UUID $KEYFILE luks" >>/etc/crypttab
grep -q "^/dev/mapper/$MAPPER " /etc/fstab || \
  echo "/dev/mapper/$MAPPER $MOUNTPT ext4 defaults,nofail 0 2" >>/etc/fstab

mkdir -p "$MOUNTPT"/{docker,qdrant,ollama,postgres,uploads,nginx-logs}

echo "[luks] done. /data is mounted and will auto-unlock at boot via $KEYFILE."
echo "[luks] NOTE: keyfile lives on the system disk; this protects against"
echo "       cloud-image exfiltration, not full host compromise."
