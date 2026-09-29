#!/bin/sh
{{{wifi_temp_probe_override}}}
for hw in /sys/class/hwmon/hwmon*; do
    [ -r "$hw/name" ] || continue
    name=$(cat "$hw/name")
    case "$name" in
        mt76*|iwlwifi|iwl*|ath11k*|ath12k*|rtw89*|brcmfmac*) ;;
        *) continue ;;
    esac
    [ -r "$hw/temp1_input" ] || continue
    milli=$(cat "$hw/temp1_input")
    printf 'wifi_temp,module=%s temp_celsius=%s\n' "$name" "$(awk "BEGIN{printf \"%.2f\", $milli/1000}")"
    exit 0
done
