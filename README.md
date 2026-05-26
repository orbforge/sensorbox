# sensorbox

Self-hosted system for building OpenWrt-based "Orb probe" images. Pick a supported device in a local web UI, provide Wi-Fi credentials and an Orb deployment token, and get an SD-card image with [Orb](https://orb.net/docs/setup-sensor/linux/openwrt) pre-installed and configured.

See [GOALS.md](GOALS.md) for the product brief and design constraints.

**Status:** early scaffolding. sensorbox builds on two upstream projects:

- [ASU](https://github.com/openwrt/asu) — consumed as the published `docker.io/openwrt/asu:latest` container image. No source lives in this repo.
- [OpenWrt Firmware Selector](https://gitlab.com/openwrt/web/firmware-selector-openwrt-org) — forked to [orbforge/firmware-selector-openwrt-org](https://github.com/orbforge/firmware-selector-openwrt-org) and included here as a git submodule at `firmware-selector/`. This is where Orb-specific UI extensions live.

The orchestration glue that wires them together is not written yet.

## Cloning

```bash
git clone --recurse-submodules git@github.com:orbforge/sensorbox.git
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init
```

## Prerequisites (macOS)

sensorbox runs on Podman because ASU's build worker spawns one container per build via the Podman API. Docker is not a drop-in substitute.

1. Install Podman and the compose wrapper:

   ```bash
   brew install podman podman-compose
   ```

   Optional GUI:

   ```bash
   brew install --cask podman-desktop
   ```

2. Initialize and start the Podman VM. The resource bumps matter — ASU's ImageBuilder runs will OOM or run out of disk on the defaults:

   ```bash
   podman machine init --cpus 4 --memory 8192 --disk-size 100
   podman machine start
   podman info   # sanity check
   ```

   `--disk-size 100` is a VM ceiling, not preallocated. ASU upstream recommends 50 GB minimum and caches grow over time.

3. After reboots or Podman upgrades:

   ```bash
   podman machine start
   ```

## Prerequisites (Linux)

Install `podman` and `podman-compose` from your distro, then enable the user socket so the ASU worker can reach it:

```bash
systemctl --user enable --now podman.socket
```

No VM needed — Podman runs natively.

## Prerequisites (Windows)

Not yet validated. Podman Desktop supports Windows via WSL2; expect a similar flow to macOS.

## Repository layout

- `firmware-selector/` — git submodule pointing at the Orb fork of the OpenWrt Firmware Selector. This is where Orb-specific UI code belongs. The submodule has `upstream` configured so you can pull improvements from openwrt: `git -C firmware-selector fetch upstream && git -C firmware-selector merge upstream/main`.
- `GOALS.md` — product brief.
- `CLAUDE.md` — guidance for Claude Code sessions working in this repo.
- `asu/` (optional, gitignored) — if you want ASU's source locally for reference or debugging: `git clone https://github.com/openwrt/asu asu`. sensorbox never builds from this directory; it's reference material only.
