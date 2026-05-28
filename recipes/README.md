# Recipes

A recipe is a single YAML file describing a device that sensorbox can build an image for. Recipes are how sensorbox stays opinionated while remaining community-extensible — adding support for a new device means adding a file here, not writing code.

## What a recipe does

At build time, the firmware-selector reads every recipe in this directory, shows the user only devices that have one, and uses the selected recipe to construct an ASU build request. The recipe supplies:

- Which OpenWrt target and profile to build for
- Which extra packages and apk feeds to include (always at least `orb`)
- Which form fields to render in the UI (via the `capabilities` section)
- A device-specific uci-defaults script that runs on first boot to configure hardware (network bridges, Wi-Fi radio, etc.)

The selector concatenates three things into the final `defaults` script sent to ASU:

1. `_common.yaml`'s `defaults` — sensorbox-wide invariants (Orb token injection, Orb apk feed persistence, root password, hostname, `orb-update install`).
2. The device recipe's `defaults` — hardware-specific configuration.
3. The user's "Additional uci-defaults (advanced)" textarea, if non-empty.

Each block is Mustache-rendered with the form inputs, then joined, then sent as ASU's `defaults` field.

**Packages** from both `_common.yaml` and the selected recipe are deduplicated and merged into a single list on the build request. `_common.yaml`'s `packages` holds dependencies needed by the shared defaults script itself (currently `micrond`, required by `orb-update`'s scheduled checks); the device recipe's `packages` holds device-specific extras (currently `orb`). The final list is sent to ASU with `diff_packages: false`, so it's interpreted as additions on top of the OpenWrt profile's defaults, not a replacement.

## Required fields

| field             | type   | notes                                                                 |
|-------------------|--------|-----------------------------------------------------------------------|
| `id`              | string | Unique identifier. Should match the OpenWrt `profile` value.          |
| `title`           | string | Human-readable name shown in the selector.                            |
| `target`          | string | OpenWrt target, e.g. `rockchip/armv8`.                                |
| `profile`         | string | OpenWrt profile, e.g. `radxa_e20c`.                                   |
| `arch`            | string | apk architecture (not target), e.g. `aarch64_generic`. Used to build the Orb feed URL. |

## Optional fields

| field             | type   | notes                                                                 |
|-------------------|--------|-----------------------------------------------------------------------|
| `description`     | string | Short blurb shown next to the title.                                  |
| `vendor_url`      | string | URL to the vendor's documentation or product page for the device. Rendered as a "Vendor docs" link in the device-info area and the download area. |
| `docs_url`        | string | URL to the orb.net setup guide for this device (e.g. `https://orb.net/docs/devices/radxa-e20c`). Rendered as an "orb.net docs" link alongside the vendor URL. |
| `install_notes`   | string | Markdown-formatted device-specific flashing and setup instructions, rendered via [snarkdown](https://github.com/developit/snarkdown) in the download area after a successful build. Supports **bold**, *italic*, [links](url), numbered/unordered lists, `code`, and headings. Use YAML block scalar (`\|`) for multi-line content. See the Radxa E20C recipe for an example. |
| `version`         | string | OpenWrt version the recipe is pinned to. Sent verbatim to ASU as the build target. Pin to a version you have actually validated on the target hardware — silent regressions across OpenWrt patch releases have broken overlay formatting, driver init, and other boot-path things for specific boards in the past. |
| `rootfs_size_mb`  | number | Optional custom rootfs partition size in MB. Sent to ASU as `rootfs_size_mb`, which ImageBuilder applies as `ROOTFS_PARTSIZE`. Useful for eMMC/SD-card devices whose physical storage is much larger than the OpenWrt profile default. |
| `capabilities`    | object | Hardware capability flags — see below.                                |
| `packages`        | list   | Extra packages beyond the profile defaults. `orb` is contributed by every recipe that wants Orb baked in. |
| `repositories`    | object | Name → URL mapping for extra apk feeds. Merged with `_common.yaml`'s repos.  |
| `repository_keys` | list   | Filenames under `recipes/keys/` holding public keys for those feeds.  |
| `defaults`        | string | Device-specific uci-defaults template. Mustache-rendered. See caveats below. |
| `install`         | object | Describes how to install this device to onboard flash (e.g. eMMC) from an SD-booted install. See the subsection below. If absent, the "Install to eMMC" form checkbox is hidden when this recipe is selected. |

## Capabilities

Capabilities describe what hardware the device has, and the UI uses them to decide which form fields to render. Everything defaults to absent.

| flag    | type | effect                                                                                  |
|---------|------|-----------------------------------------------------------------------------------------|
| `wifi`  | bool | When true, the selector renders Wi-Fi SSID, password, encryption, and band form inputs. |

The mandatory form fields — **Orb Deployment Token** and **Root Password** — are always present and always required. These are not capabilities; they are sensorbox invariants.

## Install to onboard flash (`install` block)

A recipe that declares an `install` block tells the UI that this device **can** be flashed from SD to its own onboard storage (typically eMMC) on first boot. The UI shows an "Install to eMMC on first boot" checkbox (default checked) for those recipes, and the generated uci-defaults script contains a procd init.d service that performs the copy on first boot.

The copy is **not** a full `dd` of the live SD card. It copies only the *static* parts — partition table, boot partition, and the squashfs rootfs — so there's no risk of catching a mid-write overlay page. The end of the squashfs is computed at runtime from `/sys/block/loop0/size` (the running squashfs backing) plus the start offset of the rootfs partition. The overlay tail on the SD is deliberately left behind. The eMMC boots fresh, re-runs the same uci-defaults script (from the pristine squashfs), and re-generates its own random hostname etc. — so the eMMC ends up with the same Orb token and configuration but its own settled state.

The installer also includes runtime guards so it's safe to leave enabled on every boot:

- Skips if `/etc/sensorbox-installed` exists (sentinel — already installed on this filesystem)
- Skips if the eMMC block device isn't present (handles E20C variants without onboard flash)
- Skips if no SD is inserted (post-install eMMC boots)
- On failure, sets the SYS LED to fast-blink and leaves the service enabled so the next boot retries

Fields:

| field                   | type   | notes                                                                                  |
|-------------------------|--------|----------------------------------------------------------------------------------------|
| `hint`                  | string | Short text shown below the "Install to eMMC" checkbox. Use for device-specific caveats like "not all models have eMMC" or "uncheck for SD-only testing." |
| `sd_device`             | string | Block device node of the SD card (e.g. `/dev/mmcblk1`).                                |
| `emmc_device`           | string | Block device node of the onboard flash (e.g. `/dev/mmcblk0`).                          |
| `size_from_partition`   | string | Partition name as seen under `/sys/class/block/` (e.g. `mmcblk1p2`) whose `start` sector offset plus the overlay's `loop0` offset gives the squashfs-only dd count. |
| `status_led`            | string | Kernel-exposed LED name under `/sys/class/leds/` (e.g. `green:heartbeat`). Used to signal working / done / error states during install. |

The user's install-to-eMMC choice at build time is available as Mustache variable `install_to_emmc` (boolean) for conditional section rendering.

## Templating

Every `defaults` block (both in `_common.yaml` and in each recipe) is rendered with [Mustache.js](https://github.com/janl/mustache.js) before being concatenated and sent to ASU. Available variables:

| variable          | source                                           | presence              |
|-------------------|--------------------------------------------------|-----------------------|
| `orb_token`       | Orb Deployment Token form input                  | always                |
| `root_password`   | Root Password form input                         | always                |
| `orb_apk_key`     | Contents of the first file listed in `repository_keys` — by convention this must be the Orb apk signing key. Used by `_common.yaml` to persist the feed on the running device so `orb-update` can fetch new Orb versions at runtime. | always |
| `install_to_emmc` | Whether the user checked the "Install to eMMC on first boot" form checkbox. `_common.yaml` wraps the installer block in `{{#install_to_emmc}}...{{/install_to_emmc}}` so it only appears in the script when true. | always (boolean) |
| `install_sd_device`, `install_emmc_device`, `install_size_from_partition`, `install_status_led` | Mirror of the recipe's `install` block fields. Used inside `_common.yaml`'s installer script to parameterize the dd source/target, size calculation, and LED. Empty strings when the recipe has no `install` block. | always (strings) |
| `wifi_ssid`       | Wi-Fi SSID form input                            | only if `capabilities.wifi` |
| `wifi_password`   | Wi-Fi password form input                        | only if `capabilities.wifi` |
| `wifi_encryption` | Wi-Fi encryption form selector (`psk2` default)  | only if `capabilities.wifi` |
| `wifi_band`       | Wi-Fi band selector (`auto` / `2g` / `5g` / `6g`) | only if `capabilities.wifi` |

**Use triple braces** for all variables: `{{{orb_token}}}`, not `{{orb_token}}`. Mustache by default HTML-escapes `{{ }}` variables, which corrupts shell scripts (e.g. `&` becomes `&amp;`). Triple braces produce raw output. There is no correct use of double braces in a recipe template.

For values that contain shell metacharacters (passwords most commonly), use single-quoted heredocs so the shell does not reinterpret the rendered content:

```sh
chpasswd <<'EOF'
root:{{{root_password}}}
EOF
```

This is safer than `echo '{{{root_password}}}' | ...` because it survives single quotes in the rendered value. The one thing it doesn't survive is a password containing a line that's literally `EOF` — assume users don't do that.

## uci-defaults caveats

uci-defaults scripts run very early in the first boot sequence, **before networking is up**. This means:

- `uci set` / `uci commit` works fine — you're modifying config files that network and other services will read moments later when they start normally.
- `/etc/init.d/network restart` is meaningless in this context — network hasn't started yet. Normal boot picks up your committed config automatically. Don't include these lines in a recipe.
- Any command that depends on DNS or network is a landmine. If something must run after network is up (first-boot installers, certificate fetches, etc.), drop a procd service that runs at normal init time; don't put the network-dependent command in uci-defaults.
- Scripts that exit 0 are deleted by OpenWrt after running. Scripts that exit non-zero are retained and retried on the next boot — a rough but useful retry mechanism.
- The script is written to `/etc/uci-defaults/99-asu-defaults`. It is world-readable until deletion, so the injected Orb token and root password are visible on disk during first boot. This is acceptable because sensorbox devices are ephemeral — reflash, don't reconfigure — but it is worth knowing.

## Adding a new recipe

1. Create a YAML file in this directory named after the OpenWrt profile (e.g. `friendlyarm_nanopi-r5c.yaml`).
2. Fill in the required fields, the `capabilities` block if the device has Wi-Fi, and the `defaults` script for hardware-specific setup.
3. If the device needs additional apk feeds, add them under `repositories` and commit the public keys to `recipes/keys/`.
4. Test by bringing up the stack and building an image through the browser. Flash to real hardware. GOALS.md explicitly calls out "devices should be set-it-and-forget-it" — if the resulting probe requires manual post-install steps to become useful, the recipe is incomplete.
5. Open a PR against sensorbox with the new recipe and any matching keys. Describe how you validated it on real hardware.
