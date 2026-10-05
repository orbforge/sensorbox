#!/bin/sh
echo "Content-Type: text/plain"
echo
case "$REMOTE_ADDR" in 192.168.42.*) ;;
    *) echo "403: USB-tethered network only ($REMOTE_ADDR)"; exit ;; esac
ubus call network.wireless down 2>&1
sleep 1
PHY=$(ls /sys/class/ieee80211/ 2>/dev/null | head -1)
[ -n "$PHY" ] && [ ! -d /sys/class/net/wlan0 ] && \
    iw phy "$PHY" interface add wlan0 type managed
echo "OK monitor mode ready"
iw dev
