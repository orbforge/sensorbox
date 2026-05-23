# RK3528 USB OTG / Gadget Mode on OpenWrt

Notes from getting USB peripheral mode working on the FriendlyElec NanoPi Zero2 (RK3528A) under OpenWrt's `rockchip/armv8` target, kernel 6.12. Likely applies to any RK3528 board (Radxa E20C, ROCK 2A/2F, ArmSoM Sige1) since the DWC3 controller is in the SoC, not on the board.

## TL;DR

Stock OpenWrt builds the DWC3 driver in **host-only mode** (`CONFIG_USB_DWC3_HOST=y`), so the controller can never enter peripheral mode regardless of what device tree says. The dmesg line

```
dwc3 fe500000.usb: Configuration mismatch. dr_mode forced to host
```

is *not* evidence that the silicon is host-only — it's the driver complaining that the DT asked for OTG but the *driver* can't deliver it. Rebuild the kernel with `CONFIG_USB_DWC3_DUAL_ROLE=y` + `CONFIG_USB_GADGET=y` and the controller comes up as a UDC. No glue-driver patches, no GRF programming, no vendor BSP excavation needed. The DRD support that landed in mainline via Jonas Karlman's RK3528 USB series (July 2025, in OpenWrt's `target/linux/rockchip/patches-6.12/` as `160-*` and `163-*`) is sufficient.

## Symptom

On a stock OpenWrt SNAPSHOT image for the Zero2:

```
$ dmesg | grep dwc3
[    0.580796] dwc3 fe500000.usb: Configuration mismatch. dr_mode forced to host
```

`/sys/class/typec/` is empty. `/sys/class/udc/` is empty. The USB-C port behaves as host only — plug a phone in expecting USB tethering and nothing enumerates from the phone's side.

## False trails

Things I spent time chasing that turned out to be irrelevant:

- **"GHWPARAMS0 reports HOST_ONLY"** as a hardware limitation. The "Configuration mismatch" message reads `hw_mode == HOST` from the controller's `GHWPARAMS0` register, but on RK3528 the register *does* report DRD-capable — the message fires because of the *kernel build* mismatch, not a silicon mismatch.
- **Missing `dwc3-rockchip.c` glue driver entry**. The compatible string `"rockchip,rk3528-dwc3"` in the DTS has no matching entry in `drivers/usb/dwc3/dwc3-rockchip.c`, which I assumed meant we'd need to backport vendor BSP code. In practice the controller works fine via the generic `snps,dwc3` fallback — no Rockchip-specific glue logic is needed for DRD on this SoC.
- **Heiko Stuebner's May 2026 RK3528 USB series**. Looks like the missing piece, but it's a PHY-driver respin that doesn't touch DWC3 at all. Not relevant to the OTG question.
- **Cable state at boot**. Whether the USB-C cable is connected to a power adapter vs. a host computer has no effect — the dwc3 driver decides its role at probe time (sub-second after boot), well before any USB enumeration. Empty `/sys/class/typec/` confirms there's no software-managed CC pin switching anyway; data role is fixed by board strapping.
- **U-Boot GRF programming.** Was on the list. Not needed.

## Root cause

OpenWrt's `target/linux/rockchip/armv8/config-6.12` hardcodes:

```
CONFIG_USB_DWC3=y
CONFIG_USB_DWC3_HOST=y
CONFIG_USB_DWC3_OF_SIMPLE=y
```

`CONFIG_USB_DWC3_HOST=y` selects one branch of the DWC3 driver's mutually-exclusive `MODE_SELECTION` Kconfig choice (`HOST` / `GADGET` / `DUAL_ROLE`). When `HOST` is selected, the driver is compiled without gadget code at all and `dwc3_get_dr_mode()` forces the controller to host regardless of DT.

OpenWrt's `kmod-usb-dwc3` package *does* pick `DUAL_ROLE` automatically when both `USB_SUPPORT=y` and `USB_GADGET_SUPPORT=y` are set in the OpenWrt-level config:

```make
# from package/kernel/linux/modules/usb.mk
ifeq ($(CONFIG_USB_SUPPORT)$(CONFIG_USB_GADGET_SUPPORT),yy)
  KCONFIG+= \
	CONFIG_USB_DWC3_HOST=n \
	CONFIG_USB_DWC3_GADGET=n \
	CONFIG_USB_DWC3_DUAL_ROLE=y
else
  KCONFIG+= \
	CONFIG_USB_DWC3_HOST=$(if $(CONFIG_USB_SUPPORT),y,n) \
	...
endif
```

…but the rockchip target's `config-6.12` bypasses the package model and hardcodes `HOST=y` directly, which wins.

## Fix

Append to `target/linux/rockchip/armv8/config-6.12`:

```
# CONFIG_USB_DWC3_HOST is not set
# CONFIG_USB_DWC3_GADGET is not set
CONFIG_USB_DWC3_DUAL_ROLE=y
CONFIG_USB_GADGET=y
CONFIG_USB_LIBCOMPOSITE=y
CONFIG_USB_CONFIGFS=y
CONFIG_USB_CONFIGFS_NCM=y
CONFIG_USB_F_NCM=y
```

…and replace the existing `CONFIG_USB_DWC3_HOST=y` line.

You also need to explicitly mark *every other* `USB_CONFIGFS_*` sub-option as `# CONFIG_USB_CONFIGFS_X is not set`, otherwise `make syncconfig` will hit each one as a "(NEW)" option and prompt interactively, which hangs the OpenWrt build:

```
# CONFIG_USB_CONFIGFS_SERIAL is not set
# CONFIG_USB_CONFIGFS_ACM is not set
# CONFIG_USB_CONFIGFS_OBEX is not set
# CONFIG_USB_CONFIGFS_ECM is not set
# CONFIG_USB_CONFIGFS_ECM_SUBSET is not set
# CONFIG_USB_CONFIGFS_RNDIS is not set
# CONFIG_USB_CONFIGFS_EEM is not set
# CONFIG_USB_CONFIGFS_PHONET is not set
# CONFIG_USB_CONFIGFS_MASS_STORAGE is not set
# CONFIG_USB_CONFIGFS_F_LB_SS is not set
# CONFIG_USB_CONFIGFS_F_FS is not set
# CONFIG_USB_CONFIGFS_F_HID is not set
# CONFIG_USB_CONFIGFS_F_UAC1 is not set
# CONFIG_USB_CONFIGFS_F_UAC1_LEGACY is not set
# CONFIG_USB_CONFIGFS_F_UAC2 is not set
# CONFIG_USB_CONFIGFS_F_MIDI is not set
# CONFIG_USB_CONFIGFS_F_MIDI2 is not set
# CONFIG_USB_CONFIGFS_F_PRINTER is not set
# CONFIG_USB_CONFIGFS_F_TCM is not set
# CONFIG_USB_CONFIGFS_F_UVC is not set
```

(Alternative: feed `yes "" |` into the make invocation. The explicit list is uglier but reviewable.)

`make target/linux/clean && make ...` to rebuild. The toolchain is preserved so it's ~10–15 min on an 8-core podman machine, not a full 45-min build.

## Verification on the booted device

```
$ ls /sys/class/udc/
fe500000.usb

$ cat /sys/class/udc/fe500000.usb/uevent
USB_UDC_NAME=dwc3-gadget

$ cat /sys/class/udc/fe500000.usb/state
not attached
```

`not attached` is correct here — the UDC is registered and waiting for a gadget to be bound to it. The `dwc3-gadget` UDC name confirms the dwc3 driver came up in gadget-capable mode, not host-only.

There should be **no** `Configuration mismatch` line in `dmesg` after this change. If one persists, double-check that `linux-6.12.80/.config` (the merged kernel config under `build_dir/`) shows `CONFIG_USB_DWC3_DUAL_ROLE=y` rather than `CONFIG_USB_DWC3_HOST=y`.

## Binding an NCM gadget at runtime

For one-shot testing without baking anything into the rootfs:

```sh
mount -t configfs none /sys/kernel/config
cd /sys/kernel/config/usb_gadget
mkdir orb && cd orb

echo 0x1d6b > idVendor     # Linux Foundation
echo 0x0104 > idProduct    # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "sensorbox"    > strings/0x409/manufacturer
echo "NanoPi Zero2" > strings/0x409/product
echo "0123456789"   > strings/0x409/serialnumber

mkdir -p configs/c.1/strings/0x409
echo "NCM" > configs/c.1/strings/0x409/configuration
echo 250  > configs/c.1/MaxPower

mkdir -p functions/ncm.usb0
echo "02:11:22:33:44:55" > functions/ncm.usb0/host_addr
echo "02:aa:bb:cc:dd:ee" > functions/ncm.usb0/dev_addr

ln -s functions/ncm.usb0 configs/c.1/
ls /sys/class/udc/ > UDC      # binds the gadget to the controller

ip addr add 192.168.42.1/24 dev usb0
ip link set usb0 up
```

dmesg on bind should print:

```
configfs-gadget.orb gadget.0: HOST MAC 02:11:22:33:44:55
configfs-gadget.orb gadget.0: MAC 02:aa:bb:cc:dd:ee
```

On a connected macOS host: a new NCM/USB ethernet interface appears in `System Settings → Network`. Set the Mac side manually to `192.168.42.2/24` and `ping 192.168.42.1` from either end.

iPhone is the eventual target — NCM is what iOS uses for Personal Hotspot tethering, so the iPhone-as-host direction should Just Work (CC pin role permitting). Untested in this writeup; the Mac test was the proof of concept.

## What's still open

- **Baking the gadget setup into the sensorbox recipe** — procd init.d service that sets up configfs at boot, brings up `usb0`, runs a small dnsmasq for the phone, binds `uhttpd` to the gadget interface.
- **iPhone-side empirical test** — confirm the iPhone enumerates the NCM gadget cleanly (no trust prompt expected since NCM is a generic networking class, but worth verifying).
- **Upstreaming the OpenWrt config change** — `target/linux/rockchip/armv8/config-6.12` is shared across all rockchip boards, not just RK3528. Switching DWC3 to dual-role unconditionally may surprise other boards (RK3568, RK3576, RK3588) that have been getting away with host-only. The right upstream story may be to delete the hardcoded `CONFIG_USB_DWC3_*` lines entirely and let `kmod-usb-dwc3`'s package logic pick DRD via the `USB_GADGET_SUPPORT` check.
