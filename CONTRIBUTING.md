# Contributing to orb-forge

orb-forge builds OpenWrt-based "Orb probe" images that link to an [Orb](https://orb.net) account for persistent internet monitoring. The primary way to contribute is by adding support for a new device through a **recipe** -- a single YAML file in `recipes/` that tells the build system everything it needs to know about the device: which OpenWrt target to build, which packages to include, and what uci-defaults script to run on first boot to configure the hardware.

Adding a recipe means a new device shows up in the web UI, can be built into a working Orb probe image, and (if applicable) can auto-install itself to onboard flash. No code changes are needed -- recipes are the extension point.

This guide walks through creating, testing, and submitting a recipe.

---

## Prerequisites

Before you start, you need:

1. **The physical device.** Recipes must be validated on real hardware. There is no simulator path.

2. **A working orb-forge stack.** Follow the setup instructions in [README.md](README.md) to get the Podman-based stack running (`podman-compose up`). You should be able to open `http://127.0.0.1:8080/` and see the firmware selector UI with the existing devices listed.

3. **An Orb account with a deployment token.** Sign up at [orb.net](https://orb.net), create a deployment token, and have it ready. You will need this to build and test images.

4. **OpenWrt familiarity.** You should be comfortable with uci, OpenWrt's network configuration model, and flashing images to SD cards.

5. **The device's OpenWrt support status.** Your device must have an existing OpenWrt profile in a released version (or a custom ImageBuilder -- see Phase 4 in TODO.md). Check the [OpenWrt Table of Hardware](https://openwrt.org/toh/start) and the [OpenWrt firmware selector](https://firmware-selector.openwrt.org/) to find your device's `target`, `profile`, and architecture.

---

## How to add a new recipe

### Step 1: Look up the device's OpenWrt identifiers

You need three values from OpenWrt:

- **target** -- e.g. `rockchip/armv8`, `mediatek/filogic`, `sunxi/cortexa53`
- **profile** -- the exact profile string, e.g. `radxa_e20c`, `friendlyarm_nanopi-r5c`. Find this in the OpenWrt firmware selector or in the ImageBuilder's `.profiles.json`.
- **arch** -- the apk architecture string, e.g. `aarch64_generic`. This is NOT the same as the target. It determines the Orb feed URL (`https://pkgs.orb.net/stable/openwrt-apk/<arch>/packages.adb`). For rockchip/armv8, it is `aarch64_generic`. Check `/etc/apk/arch` on a running OpenWrt install for your target if unsure.

### Step 2: Create the YAML file

Create `recipes/<profile>.yaml` (e.g. `recipes/radxa_e20c.yaml`). Use an existing recipe as your starting point:

- `recipes/radxa_e20c.yaml` -- ethernet-only device with eMMC install
- `recipes/friendlyarm_nanopi-r5c.yaml` -- device with Wi-Fi capability, options (M.2 module selection), and eMMC install

### Step 3: Fill in required fields

Every recipe must have these fields:

```yaml
id: vendor_device-name        # Must match the OpenWrt profile value
title: "Device Name"           # Human-readable, shown in the UI
target: rockchip/armv8         # OpenWrt target
profile: vendor_device-name    # OpenWrt profile (same as id)
arch: aarch64_generic          # apk architecture for the Orb feed URL
```

### Step 4: Pin a version

```yaml
version: "25.12.2"
```

Pin to a specific OpenWrt version you have validated on the hardware. Do not use "latest" or "SNAPSHOT". Silent regressions across OpenWrt patch releases have broken overlay formatting, driver init, and boot paths for specific boards. Only bump this after re-testing on real hardware.

### Step 5: Add packages, repositories, and keys

Every recipe that wants Orb baked in needs:

```yaml
packages:
  - orb

repositories:
  orb: "https://pkgs.orb.net/stable/openwrt-apk/<arch>/packages.adb"

repository_keys:
  - orb-apk-ec.pub
```

Replace `<arch>` with the actual apk architecture (e.g. `aarch64_generic`). The key file `recipes/keys/orb-apk-ec.pub` is already committed to the repo.

If your device needs additional packages beyond the profile defaults, add them to `packages`. The package list is sent to ASU with `diff_packages: false`, meaning these are **additions** on top of the OpenWrt profile's default package set, not replacements.

### Step 6: Declare capabilities

```yaml
capabilities:
  wifi: false    # or true if the device has Wi-Fi
```

Setting `wifi: true` causes the UI to render Wi-Fi form fields (SSID, password, encryption, band). If your device has no Wi-Fi, set it to `false`.

### Step 7: Add options (if applicable)

Options render as dropdowns in the UI. Each choice can add packages to the build. This is useful for devices with swappable hardware like M.2 Wi-Fi modules.

```yaml
options:
  wifi_module:
    label: "Wi-Fi Module (M.2 slot)"
    default: none
    choices:
      none:
        label: "None installed (ethernet only)"
      intel_be200:
        label: "Intel BE200 (Wi-Fi 7)"
        packages:
          - kmod-iwlwifi
          - iwlwifi-firmware-be200
          - -wpad-basic-mbedtls     # - prefix removes the basic variant
          - wpad-mbedtls
          - iw
```

See `recipes/friendlyarm_nanopi-r5c.yaml` for a complete example.

### Step 8: Write the defaults block

The `defaults` block is a uci-defaults shell script template rendered with [Mustache.js](https://github.com/janl/mustache.js). It runs on first boot, before networking is up. This is where you configure the device's hardware: bridge ports, set up Wi-Fi, configure LEDs, etc.

The `_common.yaml` pre-amble (Orb token injection, root password, hostname, orb-update, apk feed persistence) is prepended automatically. Your recipe's `defaults` only needs device-specific setup.

A typical ethernet-only recipe bridges both ports as a DHCP client:

```yaml
defaults: |
  # Bridge both ethernet ports as a single DHCP client.
  uci set network.lan.device='br-lan'
  uci set network.lan.proto='dhcp'
  uci -q delete network.lan.ipaddr
  uci -q delete network.lan.netmask
  uci set network.@device[0]=device
  uci set network.@device[0].name='br-lan'
  uci set network.@device[0].type='bridge'
  uci set network.@device[0].ports='eth0 eth1'
  uci commit network

  # Remove stock WAN configuration.
  uci -q delete network.wan
  uci -q delete network.wan6
  uci commit network
```

**Templating rules:**

- Use **triple braces** for all variables: `{{{orb_token}}}`, not `{{orb_token}}`. Double braces HTML-escape the output, which corrupts shell scripts.
- Available variables: `orb_token`, `root_password`, `wifi_ssid`, `wifi_password`, `wifi_encryption`, `wifi_band`, `install_to_emmc`, and the `install_*` variables. See `recipes/README.md` for the full list.
- Wrap Wi-Fi configuration in `{{#wifi_ssid}}...{{/wifi_ssid}}` so it only renders when the user provides an SSID.

**uci-defaults caveats:**

- Scripts run before networking is up. Do not call anything that needs DNS or network access.
- `uci set` / `uci commit` works fine -- services read the committed config when they start normally.
- Do NOT include `/etc/init.d/network restart` -- it is meaningless before the network has started.
- Scripts that exit 0 are deleted after running. Scripts that exit non-zero are retained and retried on next boot.

### Step 9: Add the install block (eMMC devices)

If the device has onboard flash (eMMC), add an `install` block so users can auto-install from SD to eMMC on first boot:

```yaml
install:
  hint: "Not all models have eMMC. Uncheck for SD-only operation."
  sd_device: /dev/mmcblk1       # Block device of the SD card
  emmc_device: /dev/mmcblk0     # Block device of the onboard flash
  size_from_partition: mmcblk1p2 # Partition name under /sys/class/block/
  status_led: "green:heartbeat" # LED under /sys/class/leds/ for status
```

**Important:** The SD and eMMC device mappings vary between boards. On the Radxa E20C, `mmcblk1` is the SD and `mmcblk0` is the eMMC. On the NanoPi R5C, it is reversed (`mmcblk0` is SD, `mmcblk1` is eMMC). Boot from SD with a stock OpenWrt image and check `lsblk` or `/sys/class/block/` to determine which is which on your device.

The `status_led` must be a kernel-exposed LED name visible under `/sys/class/leds/`. Run `ls /sys/class/leds/` on the device to find valid names.

### Step 10: Add install_notes, vendor_url, docs_url

```yaml
vendor_url: "https://example.com/product-page"
docs_url: "https://orb.net/docs/devices/your-device"
install_notes: |
  1. Flash the downloaded image to an **SD card** using balenaEtcher or `dd`.
  2. Insert the SD card and connect power.
  3. If **Install to eMMC** is enabled: watch the status LED...
  ...
```

`install_notes` supports Markdown (bold, italic, links, lists, code, headings) rendered via snarkdown in the download area. Write instructions specific to your device -- LED behavior, port layout, quirks.

### Step 11: Add a description

```yaml
description: "Short blurb about the device shown in the selector UI."
```

---

## End-to-end testing checklist

Every recipe must be validated on real hardware before submission. Do not skip items.

### Build and flash

- [ ] Build an image via the web UI at `http://127.0.0.1:8080/` with a real Orb deployment token and root password.
- [ ] Flash the resulting image to an SD card (balenaEtcher, `dd`, etc.).
- [ ] Insert the SD card into the device and power on.

### Core functionality (every device)

- [ ] **Hostname:** Verify the device has a unique random hostname (`Orb-NNNN`). Check via SSH prompt or `uci get system.@system[0].hostname`.
- [ ] **Root password:** SSH into the device using the root password you set in the form. Confirm it works.
- [ ] **Orb running:** `ps | grep orb` shows the Orb process.
- [ ] **Orb token configured:** `cat /etc/config/orb` shows the deployment token you entered.
- [ ] **orb-update registered:** `ls /etc/init.d/ | grep orb` shows `orb-update` (or equivalent).
- [ ] **Orb apk feed persisted:** `cat /etc/apk/repositories.d/customfeeds.list` contains `https://pkgs.orb.net/stable/openwrt-apk/<arch>/packages.adb`.
- [ ] **Network config:** Verify the network configuration matches the recipe's intent. For bridged ethernet: both ports should be in `br-lan`, `proto` should be `dhcp`, no static IP assigned, no DHCP server running. Check with `uci show network`.

### Wi-Fi (if `capabilities.wifi: true`)

- [ ] **Wireless association:** `iw dev <interface> link` shows "Connected to" with the expected SSID.
- [ ] **Internet reachable over Wi-Fi:** With ethernet unplugged, `ping -c3 1.1.1.1` succeeds.
- [ ] **Band behavior:** If the user selected a specific band, verify the device connected on that band. If "auto", verify the device connected on any available band.
- [ ] **wwan metric:** `uci get network.wwan.metric` returns a value (e.g. `20`) so ethernet is preferred for default route when both are connected.

### eMMC install (if `install` block present)

- [ ] **LED feedback during install:** The status LED blinks during the eMMC write.
- [ ] **All LEDs pulse on completion:** When the install finishes, ALL LEDs on the device pulse in unison.
- [ ] **Boot from eMMC:** Power off, remove the SD card, power on. The device boots from eMMC.
- [ ] **Different hostname on eMMC:** The eMMC-booted device has a different `Orb-NNNN` hostname than the SD boot, confirming fresh overlay and uci-defaults re-run.
- [ ] **Orb running on eMMC:** `ps | grep orb` shows the Orb process on the eMMC boot.
- [ ] **PARTUUID collision test:** Re-insert the SD card with eMMC still installed. Power on. Verify the device boots from the SD card (check hostname -- it should be the SD hostname, not the eMMC one). This confirms the installer's disk-signature randomization is working and the eMMC's PARTUUID does not hijack SD boots.
- [ ] **install_notes accuracy:** Re-read the `install_notes` you wrote and confirm every step matches what actually happens on the hardware (LED names, port locations, timing).

---

## Common pitfalls

These are real issues encountered during development. Save yourself time by reading them before you start.

### diff_packages must be false

Recipes declare package **additions**, not replacements. The selector sends the merged package list to ASU with `diff_packages: false`. If this were `true`, ASU would interpret `packages: ["orb"]` as the complete package list and silently strip base-files, busybox, and everything else. The result is a broken image with missing applets, no hostname binary, no password utilities -- and no obvious error message.

### The eMMC installer copies only the read-only squashfs, not the live overlay

The `dd` copies sectors from the start of the disk through the end of the squashfs (computed from `/sys/block/loop0/size` plus partition offsets). It deliberately excludes the overlay tail of the rootfs partition. The eMMC boots with a fresh overlay and re-runs uci-defaults from the pristine squashfs. This is by design -- the eMMC gets the same Orb token and config but its own clean state.

### PARTUUID collision after dd

After `dd` to eMMC, both the SD and eMMC have identical MBR disk signatures (OpenWrt's default `OWRT` signature, producing `PARTUUID=5452574f-02`). Without mitigation, the kernel finds the eMMC first during enumeration, and all "SD boots" silently boot from eMMC instead. The installer randomizes the eMMC's 4-byte disk signature at MBR offset 440 after a successful write. If you are writing a custom install flow, you must do the same.

### eMMC boot partitions may have factory bootloaders

Some boards (e.g. NanoPi R5C) ship with factory Armbian or vendor SPL in the eMMC's hardware boot partitions (`boot0`/`boot1`). The Rockchip BROM loads from `boot0` first, which overrides the OpenWrt SPL written to the main area by `dd`. The installer zeros `boot0` and `boot1` (after clearing `force_ro`) to force the BROM to fall through. If your device uses a different SoC boot sequence, check whether hardware boot partitions are interfering.

### Wi-Fi wwan interface needs a metric for default route failover

When a device has both ethernet and Wi-Fi, both interfaces get DHCP leases and both advertise a default route. Without a metric on the `wwan` interface, the routing table has two equal-cost defaults and behavior is unpredictable. Set `uci set network.wwan.metric='20'` (or similar) so ethernet is preferred and Wi-Fi is failover.

### Some busybox builds are stripped

The default OpenWrt busybox build for some targets compiles out `chpasswd`, `hostname`, `blkid`, and `logread`. Do not rely on `chpasswd` in your defaults script. Use `passwd` with a heredoc instead:

```sh
passwd root >/dev/null 2>&1 <<'PWEOF' || true
{{{root_password}}}
{{{root_password}}}
PWEOF
```

This is already handled by `_common.yaml`, so you do not need to set the root password in your recipe. But be aware of it if you need other busybox applets.

### SD I/O contention during dd

Using `bs=512` (the default) for a large dd from SD to eMMC means hundreds of thousands of individual reads from the SD card. This starves the kernel's concurrent squashfs reads and causes "xz decompression failed" I/O errors. The installer uses `bs=1M` to reduce operations. If you write any dd commands in your recipe, use a large block size.

### The installer must be invoked directly from uci-defaults

The eMMC installer is created as an init.d service at `START=20`, but by the time uci-defaults runs and creates the service file, procd may have already iterated past that start priority. The installer is therefore invoked directly from uci-defaults (backgrounded with `&`) in addition to being enabled as a service. The service stays enabled as a fallback for retry on next boot if the direct invocation fails. If you are adding any similar first-boot service, follow this pattern.

### SD vs eMMC device node mapping is board-specific

Do not assume `mmcblk0` is always the SD card. On the Radxa E20C, `mmcblk0` is eMMC and `mmcblk1` is SD. On the NanoPi R5C, it is reversed. Boot from SD with a stock image and check `lsblk` to determine the mapping for your board.

---

## Submitting your recipe

1. **Branch and commit.** Create a branch in your fork of orb-forge with the new recipe file (`recipes/<profile>.yaml`) and any new signing keys under `recipes/keys/`.

2. **Open a PR against orb-forge.** In the PR description, include:
   - The device name and where you purchased it.
   - The OpenWrt version validated (must match the recipe's `version` field).
   - Which items from the testing checklist above you completed, and their results.
   - Any device-specific quirks you discovered (LED naming, port mapping, boot behavior, thermal issues, etc.).
   - Photos of the device with LED states during install (helpful but not required).

3. **Expect hardware-level review.** Recipe PRs will be reviewed for correctness of the uci-defaults script, completeness of the install block, and accuracy of the install_notes. If the reviewer does not have the same hardware, they may ask follow-up questions or request additional test evidence.

4. **One recipe per PR.** Keep PRs focused on a single device. If you are adding multiple devices, submit separate PRs.
