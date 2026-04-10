# Recipes

A recipe is a single YAML file describing a device that orb-forge can build an image for. Recipes are how orb-forge stays opinionated while remaining community-extensible — adding support for a new device means adding a file here, not writing code.

## What a recipe does

At build time, the firmware-selector reads every recipe in this directory, shows the user only devices that have one, and uses the selected recipe to construct an ASU build request. The recipe supplies:

- Which OpenWrt target and profile to build for
- Which extra packages and apk feeds to include (always at least `orb`)
- Which form fields to render in the UI (via the `capabilities` section)
- A device-specific uci-defaults script that runs on first boot to configure hardware (network bridges, Wi-Fi radio, etc.)

The selector concatenates three things into the final `defaults` script sent to ASU:

1. `_common.yaml`'s `defaults` — orb-forge-wide invariants (Orb token injection, `orb-update install`, root password).
2. The device recipe's `defaults` — hardware-specific configuration.
3. The user's "Additional uci-defaults (advanced)" textarea, if non-empty.

Each block is Mustache-rendered with the form inputs, then joined, then sent as ASU's `defaults` field.

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
| `min_version`     | string | Minimum OpenWrt version this recipe targets. Recipes for devices requiring 25.12+ for apk should set this. |
| `capabilities`    | object | Hardware capability flags — see below.                                |
| `packages`        | list   | Extra packages beyond the profile defaults. `orb` is contributed by every recipe that wants Orb baked in. |
| `repositories`    | object | Name → URL mapping for extra apk feeds. Merged with `_common.yaml`'s repos.  |
| `repository_keys` | list   | Filenames under `recipes/keys/` holding public keys for those feeds.  |
| `defaults`        | string | Device-specific uci-defaults template. Mustache-rendered. See caveats below. |

## Capabilities

Capabilities describe what hardware the device has, and the UI uses them to decide which form fields to render. Everything defaults to absent.

| flag    | type | effect                                                                                  |
|---------|------|-----------------------------------------------------------------------------------------|
| `wifi`  | bool | When true, the selector renders Wi-Fi SSID, password, encryption, and band form inputs. |

The mandatory form fields — **Orb Deployment Token** and **Root Password** — are always present and always required. These are not capabilities; they are orb-forge invariants.

## Templating

Every `defaults` block (both in `_common.yaml` and in each recipe) is rendered with [Mustache.js](https://github.com/janl/mustache.js) before being concatenated and sent to ASU. Available variables:

| variable          | source                                           | presence              |
|-------------------|--------------------------------------------------|-----------------------|
| `orb_token`       | Orb Deployment Token form input                  | always                |
| `root_password`   | Root Password form input                         | always                |
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
- The script is written to `/etc/uci-defaults/99-asu-defaults`. It is world-readable until deletion, so the injected Orb token and root password are visible on disk during first boot. This is acceptable because orb-forge devices are ephemeral — reflash, don't reconfigure — but it is worth knowing.

## Adding a new recipe

1. Create a YAML file in this directory named after the OpenWrt profile (e.g. `friendlyarm_nanopi-r5c.yaml`).
2. Fill in the required fields, the `capabilities` block if the device has Wi-Fi, and the `defaults` script for hardware-specific setup.
3. If the device needs additional apk feeds, add them under `repositories` and commit the public keys to `recipes/keys/`.
4. Test by bringing up the stack and building an image through the browser. Flash to real hardware. GOALS.md explicitly calls out "devices should be set-it-and-forget-it" — if the resulting probe requires manual post-install steps to become useful, the recipe is incomplete.
5. Open a PR against orb-forge with the new recipe and any matching keys. Describe how you validated it on real hardware.
