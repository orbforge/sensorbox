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

- **ASU** (Attended Sysupgrade Server, https://github.com/openwrt/asu, GPL-2.0). **Consumed as the published `docker.io/openwrt/asu:latest` container image.** No source in this repo — not vendored, not a submodule, gitignored if cloned locally. Extend via compose config, env vars, sidecars, or forked ImageBuilder inputs, never by patching ASU itself. Reasons we need it (from GOALS.md): bake in Orb, build from branches/forks while waiting on kernel/OpenWrt merges, ship proprietary or source-built Wi-Fi drivers (e.g. Intel BE200). Python/FastAPI + RQ workers + Redis; its worker spawns per-build containers via the **Podman** API (not Docker — see "Why Podman" below).
- **Firmware Selector** (upstream GitLab: openwrt/web/firmware-selector-openwrt-org). Forked to https://github.com/dboze/firmware-selector-openwrt-org and included as a **git submodule at `firmware-selector/`**. This is where Orb-specific UI code belongs. The submodule has an `upstream` remote configured for syncing improvements from OpenWrt. Configurable knobs the Orb UI must expose (per GOALS.md): supported Wi-Fi card, SSID/security/password, `ORB_DEPLOYMENT_TOKEN`, root password, Wi-Fi band policy (auto / 2.4 / 5 / 6 GHz). Future nice-to-have: pointing the device at the local ASU for periodic security upgrades.
- `asu/` — gitignored. Optional local reference clone of upstream ASU for reading code while debugging. Never referenced by compose or build.
- `GOALS.md` — product brief.

**Working in the submodule:** if you edit anything under `firmware-selector/`, you're making commits in the fork repo, not in orb-forge. Commit and push inside the submodule first, then come back to orb-forge and commit the updated submodule pointer. `git status` in orb-forge will show `firmware-selector` as "modified" until you do.

## Why Podman (not Docker)

ASU's build worker imports `podman-py` and talks to the Podman REST API over a Unix socket to spawn one container per build. Docker's socket speaks a different API — pointing `CONTAINER_SOCKET_PATH` at `/var/run/docker.sock` will not work. We committed in GOALS.md to not modifying ASU, so swapping to docker-py is off the table. The stack is Podman-only. On macOS this means `podman machine` (a Linux VM under the hood); see README.md for setup and the resource bumps that matter for ImageBuilder runs.

## Working with the subprojects

### ASU (consumed as published image)

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
