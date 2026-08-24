#!/bin/sh
# One-time: let your existing 'wheel' membership open the DUT console.
#
# Uses GROUP="wheel" rather than the conventional "uucp" deliberately: you are
# already in wheel, so this takes effect as soon as udev retriggers. Adding
# your user to uucp would need a full logout/login before it applied.
#
#   sudo hwtest/setup/grant-serial.sh

set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

cat > /etc/udev/rules.d/70-sensorbox-serial.rules <<'RULE'
# CH340 USB-serial adapter used for the sensorbox DUT console
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", GROUP="wheel", MODE="0660"
RULE

udevadm control --reload-rules
udevadm trigger --subsystem-match=tty
echo "done: $(ls -l /dev/ttyUSB0 2>/dev/null || echo '/dev/ttyUSB0 not present')"
