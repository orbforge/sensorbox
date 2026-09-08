#!/bin/sh
# One-time: let an UNPRIVILEGED tftpd serve U-Boot, which hardcodes port 69.
#
# Lowering net.ipv4.ip_unprivileged_port_start would also hand every user
# process ports 80/443/123, so instead this redirects only UDP/69 to 6969.
# The server itself never runs as root. Scoped to its own nft table, so
# removal is one command:
#
#   sudo hwtest/setup/grant-tftp.sh          # install
#   sudo hwtest/setup/grant-tftp.sh --undo   # remove

set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

if [ "${1:-}" = "--undo" ]; then
    nft delete table inet sensorbox 2>/dev/null && echo "removed" || echo "nothing to remove"
    exit 0
fi

nft delete table inet sensorbox 2>/dev/null || true
nft add table inet sensorbox
nft add chain inet sensorbox prerouting '{ type nat hook prerouting priority dstnat; policy accept; }'
nft add rule inet sensorbox prerouting udp dport 69 redirect to :6969

echo "rule installed:"
nft list table inet sensorbox | sed 's/^/  /'
