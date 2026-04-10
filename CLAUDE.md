# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

orb-forge is an opinionated, self-hosted system for building OpenWrt-based "Orb probe" images that link to an Orb account for persistent-internet monitoring. A user runs the stack locally (target: `docker-compose up` on macOS/Windows/Linux), picks a device + options in a web UI, and gets an SD-card image with Orb pre-installed and credentials baked in via `uci-defaults`.

Read `GOALS.md` first — it is the source of truth for product intent and constraints. Key invariants that must shape design decisions:

- **Initial target devices:** NanoPi R5C (ethernet + Wi-Fi) and Radxa E20C (ethernet-only). Others come later.
- **Opinionated, not configurable.** When in doubt, remove a knob rather than add one.
- **Devices are ephemeral / "set it and forget it."** Reconfiguration = reflash, not SSH. Don't design runtime admin flows.
- **Sensitive data (Wi-Fi creds, `ORB_DEPLOYMENT_TOKEN`, root password) is baked into images** via uci-defaults. This is the reason the stack must run locally — never push these through a public ASU/firmware-selector.
- **Network defaults:** Wi-Fi and ethernet act as DHCP clients (no DHCP server). Wi-Fi is band-agnostic unless the user pins it.
- **Orb install reference:** https://orb.net/docs/setup-sensor/linux/openwrt — Orb is not in public OpenWrt repos, so ASU is used to bake it in.

## Repository layout

orb-forge is licensed MIT. It depends on two upstream OpenWrt projects handled very differently:

- **ASU** (Attended Sysupgrade Server, https://github.com/openwrt/asu, GPL-2.0). Built from the **`asu/` submodule pointing at `dboze/asu` on the `orb-patches` branch**. The `orb-patches` branch is upstream `openwrt/asu` main with a four-commit cherry-pick of open PR **openwrt/asu#1590** ("Support additional apk feeds" by andibraeu) applied on top. This cherry-pick is the minimum ASU needs to support **custom apk package feeds in `append` mode** — which orb-forge requires to bake the `orb` package into 24.10+/25.xx images at build time without losing the stock OpenWrt feeds. PR #1590 (not #1589; see below) is the right one because it preserves the default `packages.adb` feeds; #1589 only supports replace-mode and causes "impossible package selection" errors for every stock package. A scheduled remote trigger at https://claude.ai/code/scheduled/trig_01QQw8LgQs5KLPTGdhkEQCia checks daily whether PR #1590 has merged upstream; when it does, the next interactive session should switch the submodule URL back to `openwrt/asu` directly and the fork becomes vestigial. Both `asu-server` and `asu-worker` in `compose.yaml` build from this submodule using upstream's `Containerfile` (unmodified) and tag the resulting image as `localhost/orb-forge/asu:orb-patches`. Python/FastAPI + RQ workers + Redis; the worker spawns per-build containers via the **Podman** API (not Docker — see "Why Podman" below).
- **Firmware Selector** (upstream GitLab: openwrt/web/firmware-selector-openwrt-org). Forked to https://github.com/dboze/firmware-selector-openwrt-org and included as a **git submodule at `firmware-selector/`**. This is where Orb-specific UI code belongs. The submodule has an `upstream` remote configured for syncing improvements from OpenWrt. Configurable knobs the Orb UI must expose (per GOALS.md): supported Wi-Fi card, SSID/security/password, `ORB_DEPLOYMENT_TOKEN`, root password, Wi-Fi band policy (auto / 2.4 / 5 / 6 GHz). Future nice-to-have: pointing the device at the local ASU for periodic security upgrades.
- `asu/` — git submodule (see above). Source lives here; compose builds the image from it.
- `GOALS.md` — product brief.

**Working in the submodule:** if you edit anything under `firmware-selector/`, you're making commits in the fork repo, not in orb-forge. Commit and push inside the submodule first, then come back to orb-forge and commit the updated submodule pointer. `git status` in orb-forge will show `firmware-selector` as "modified" until you do.

## Why Podman (not Docker)

ASU's build worker imports `podman-py` and talks to the Podman REST API over a Unix socket to spawn one container per build. Docker's socket speaks a different API — pointing `CONTAINER_SOCKET_PATH` at `/var/run/docker.sock` will not work. We committed in GOALS.md to not modifying ASU, so swapping to docker-py is off the table. The stack is Podman-only. On macOS this means `podman machine` (a Linux VM under the hood); see README.md for setup and the resource bumps that matter for ImageBuilder runs.

## Working with the subprojects

### ASU (built from submodule with PR #1590 cherry-pick)

**Baking the `orb` package into images.** The Orb apk feed lives at `https://pkgs.orb.net/stable/openwrt-apk/$ARCH/packages.adb` and is signed by `orb-apk-ec.pub` (EC key). To include Orb in a build, the ASU build request must set:

- `packages` including `"orb"`
- `repositories = {"orb": "https://pkgs.orb.net/stable/openwrt-apk/<arch>/packages.adb"}`
- `repositories_mode = "append"` — **do not omit this**; the default is `"replace"`, which drops the stock OpenWrt feeds and makes every standard package unresolvable.
- `repository_keys = ["<contents of orb-apk-ec.pub>"]`
- `REPOSITORY_ALLOW_LIST` in ASU's env must include `"https://pkgs.orb.net/stable/openwrt-apk/"` (already set in `.env.example`). Empty allow list = ASU denies *all* custom repos.

This has been validated end-to-end for rockchip/armv8 radxa_e20c on OpenWrt 25.12.2 — orb 1.4.11 landed in the image manifest.

**Architecture string for the feed URL** is the apk arch (e.g. `aarch64_generic`), not the OpenWrt target. rockchip/armv8 → `aarch64_generic`. This is *not* automatically derivable from the target in the current code path; the client has to send the right URL per target. When the firmware-selector fork learns to send Orb repos by default, it'll need a small arch lookup table.

**Legacy info.**

- Python project managed with `uv`; entrypoint `asu/main.py` (FastAPI).
- Runs as a multi-container stack via `podman-compose.yml` (server + Podman API + worker + Redis). Builds happen **inside containers** for isolation — don't try to run ImageBuilder directly on the host.
- `ALLOW_DEFAULTS=1` in the ASU env is required for the custom uci-defaults script flow that orb-forge depends on (baking in credentials).
- Dev commands (run from `asu/`, only if you need to hack on ASU itself — normally you won't):
  - `uv sync --extra dev`
  - `uv run fastapi dev asu/main.py`
  - `uv run rq worker` (needs `source .env` first)
- Tests live under `asu/tests/`.

Because this is GPL-2.0 and we've committed to not modifying it, any Orb-specific behavior should live in orb-forge's own layer (compose file, config, sidecar service, or fork of firmware-selector), not in patches to `asu/`.

### `firmware-selector/` (submodule of the Orb fork)

- Plain HTML/CSS/JS under `www/`; no build step for the app itself.
- Local run: `python3 -m http.server` from the subproject root, then open `http://localhost:8000/www/`.
- Config lives in `www/config.js`. Per-device extra packages live in `www/device_packages.json` (see `device_packages.json.example`) — this is the mechanism for attaching the Intel BE200 driver and similar device-specific packages.
- uci-defaults scripts authored in the selector land in `/etc/uci-defaults/` on the built image and run once on first boot — this is the injection point for Orb deployment token, root password, and Wi-Fi credentials.
- Tests: `node --test 'tests/js/*.test.js'` (Node 18+), or `yarn run test:unit` / `yarn run test:coverage`.

## Architectural notes for future work

- The end-state is a single `docker-compose`/`podman-compose` stack combining ASU + an Orb-flavored firmware selector + any supporting services, runnable cross-platform with one command. ASU upstream ships `podman-compose.yml`; the orb-forge compose file will likely wrap or reference it rather than duplicate it.
- Orb integration into images has to go through ASU (custom package feed or ImageBuilder inputs) because Orb isn't in public OpenWrt repos.
- Credential injection path: firmware-selector UI form → uci-defaults script → ASU build request → image. Keep this path local-only; never expose it to the public internet without explicit user acknowledgement.
- Device support beyond NanoPi R5C / Radxa E20C may require custom ImageBuilder branches — design the ASU integration so swapping in a forked ImageBuilder per device is straightforward.
