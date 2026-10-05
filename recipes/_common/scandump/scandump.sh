#!/bin/sh
# Thin wrapper around ghcr.io/dboze/scandump (sensorbox).
# Behaves like a native scandump binary: stdin/stdout/stderr stream
# through, signals (SIGINT, SSH SIGHUP) propagate via exec, /tmp is
# bind-mounted so file output to /tmp/scan.pcap lands on the host.
# --network host so the container sees wlan0/phy0.
# NET_ADMIN + NET_RAW are the minimum caps scandump needs for nl80211.
exec docker run --rm -i \
    --network host \
    --cap-add NET_ADMIN \
    --cap-add NET_RAW \
    -v /tmp:/tmp \
    ghcr.io/dboze/scandump:latest "$@"
