#!/bin/sh
echo "Content-Type: text/plain"
echo
case "$REMOTE_ADDR" in 192.168.42.*) ;;
    *) echo "403: USB-tethered network only ($REMOTE_ADDR)"; exit ;; esac
iw dev wlan0 del 2>/dev/null
for mon in $(iw dev | awk '/Interface/{print $2}' | grep '^itb'); do
    iw dev "$mon" del 2>/dev/null
done
ubus call network.wireless up 2>&1
echo "OK restored"
sleep 2
iw dev
