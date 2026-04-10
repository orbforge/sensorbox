# TODO

Living roadmap derived from GOALS.md and ongoing design discussions. Organized by phase, not priority within a phase. When something ships, move it to a "Done" section at the bottom rather than deleting — the history is useful context.

## Phase 1 — Recipe system MVP

Goal: one supported device (Radxa E20C) built end-to-end from a recipe, through a form with mandatory Orb token + root password fields, no free-form hack paths required to get a working probe.

- [ ] Create `recipes/` directory with authoring README describing the YAML shape, conventions, and how recipes are consumed.
- [ ] Write `recipes/radxa_e20c.yaml` with the E20C bridge-both-ethernet uci-defaults block (user-provided, minus the `/etc/init.d/network restart` tail that's meaningless in uci-defaults context).
- [ ] Write `recipes/_common.yaml` with the Orb-wide pre-amble: `/etc/config/orb` token injection, `orb-update install`, root password setup via `passwd`.
- [ ] Commit `recipes/keys/orb-apk-ec.pub` so the key is version-controlled rather than fetched at runtime.
- [ ] Vendor `js-yaml` and `mustache.js` into `firmware-selector/www/js/vendor/` in the fork (two files, ~27 KB gzipped total).
- [ ] Fork work: fetch `recipes/*.yaml` via HTTP from the selector's own origin (nginx serves them directly from an orb-forge bind mount into the selector container).
- [ ] Fork work: replace upstream's `.overview.json`-driven device list with a recipe-driven one. Devices without a recipe do not appear.
- [ ] Fork work: render form fields — Orb Deployment Token (required), Root Password (required), plus capability-gated fields (Wi-Fi SSID/pass/encryption/band if `capabilities.wifi`).
- [ ] Fork work: collapse the upstream free-form uci-defaults textarea behind an "Advanced" disclosure, renamed "Additional uci-defaults (advanced)." Append-after-recipe semantics.
- [ ] Fork work: build request assembly — Mustache-render `_common.defaults` + recipe `defaults` + optional advanced textarea → single `defaults` string. Send `packages`, `repositories`, `repositories_mode: "append"`, `repository_keys`, `defaults` to ASU.
- [ ] Mount `recipes/` into the selector container via compose.yaml so edits are live.
- [ ] End-to-end test: build an E20C image via the browser with a real Orb token, flash, verify the device boots, bridges both ethernet ports, pulls DHCP on whichever port is plugged in, links to the Orb account automatically, and has auto-updates enabled. Also close the loop on `orb-update install`: confirm exactly what it registers on the running device (crontab entry? init.d script? something else?) so `_common.yaml` can be hardened if the current one-liner turns out to be insufficient. Hardware is on hand and ready.

## Phase 2 — Install to eMMC

Context: most of the devices we care about (E20C, NanoPi R5C, future boards) have onboard eMMC. The intended deployment flow is "insert SD, power on, let the device copy itself to eMMC, remove SD, reboot, run forever." Without this step, every probe is permanently dependent on an SD card, which contradicts GOALS.md's "set it and forget it" principle and the broader UX intent.

The mechanism is device-specific (which eMMC device node to target, which device node we booted from, whether a vendor tool exists), so this work lives in recipes.

- [ ] Decide on the installer pattern. Candidates: (a) a boot-time init.d service that checks whether rootfs is SD, writes to eMMC via `dd` or `sysupgrade`, and signals completion; (b) use an existing OpenWrt `emmc-install` or similar package if one exists for rockchip targets; (c) a custom script shipped by `_common.yaml` with per-recipe parameters. Likely (c) with the recipe declaring devices and LED hooks.
- [ ] Extend the recipe schema with an `install` section: `{ to_emmc: bool, sd_device, emmc_device, status_leds }` or similar. E20C recipe populates it with real values.
- [ ] `_common.yaml` drops a first-boot installer script that reads the recipe-provided device paths and executes the copy. Either via uci-defaults (runs early, may need to be split from the main defaults to run after networking is up so the user knows what's happening) or via a procd service that self-disables after one successful run.
- [ ] LED feedback: during install, blink a configurable "working" LED; on success, solid "done" LED; on failure, blink an error pattern. LED GPIO paths are per-device and go in the recipe. LEDs controlled via `/sys/class/leds/<name>/` or `echo timer > trigger`. See OpenWrt's led config docs.
- [ ] First-run detection: mark eMMC as "installed" via a sentinel file (e.g. `/etc/orb-forge-installed`) so reboots after install don't re-trigger the flow. On SD-booted systems where no install has happened, the service runs; on eMMC-booted systems or SD systems where install is complete, the service exits immediately.
- [ ] Hardware test on E20C: flash SD, power on, verify the device runs the install, signals via LEDs, survives a power cycle after SD removal, and continues to link to Orb and auto-update from eMMC.
- [ ] Failure mode documentation in `recipes/README.md`: what happens if eMMC write fails mid-flight, how to recover, how to force a re-install.

## Phase 3 — Second device + Wi-Fi capability

- [ ] `recipes/nanopi_r5c.yaml`. This is the Wi-Fi capable device from GOALS.md.
- [ ] Figure out the BE200 driver story — it's mentioned as the hard example in GOALS.md. Check whether there's an OpenWrt package or if it needs buildroot work.
- [ ] Exercise Wi-Fi form fields end-to-end: SSID, password, encryption (psk2 default), band policy (auto / 2.4 / 5 / 6 GHz — GOALS.md calls out each).
- [ ] Wi-Fi `uci` commands in the recipe's `defaults` template, with Mustache vars for user-provided values.
- [ ] Network defaults from GOALS.md: Wi-Fi acts as client, no DHCP server, not pinned to a specific band unless the form says otherwise.

## Phase 4 — Custom ImageBuilder pipeline (NanoPi Zero2 unblocker)

- [ ] `openwrt-builder/` directory in orb-forge: holds patches, DTS, profile snippets, and a reproducible build script (`build.sh` or `Dockerfile.builder`).
- [ ] Populate with the NanoPi Zero2 material referenced in https://github.com/openwrt/openwrt/pull/22707 — the branch in `dboze/openwrt` is the source.
- [ ] `imagebuilder-host` service in compose: nginx sidecar serving the produced ImageBuilder tarballs so ASU can pull from `http://imagebuilder-host/...` instead of `downloads.openwrt.org`.
- [ ] ASU configuration path (env or branches.yaml override) that routes specific (version, target) combinations to the local sidecar.
- [ ] `recipes/friendlyarm_nanopi-zero2.yaml` pinning to the custom ImageBuilder version.
- [ ] CI job (GitHub Actions?) that rebuilds the custom ImageBuilder on each update to the patches or DTS.
- [ ] When PR #22707 merges upstream, drop the custom path for this device and fall back to stock ImageBuilder.

## Radxa E20C stripped-busybox workaround — follow up

On OpenWrt 25.12.0 and 25.12.2 for rockchip/armv8 radxa_e20c, busybox ships with applets like `hostname`, `chpasswd`, `blkid`, and `logread` compiled OUT. `/etc/config/system` ships empty, so the device boots as `(none)` with no hostname. `_common.yaml` currently papers over all of this by populating `/etc/config/system` with a random `Orb-NNNN` hostname and writing `/proc/sys/kernel/hostname` directly. The password-setting line uses `passwd` with a stdin heredoc instead of `chpasswd`.

This is a band-aid. The real fix is one of:

- [ ] Add `coreutils-hostname` (or equivalent) to the E20C recipe's `packages` so the device has a real `hostname` binary.
- [ ] Investigate whether a full (non-stripped) busybox can be installed via the apk feed on this target. May not be possible if busybox is compiled monolithically into the base image — in which case the feed package would be a no-op.
- [ ] If the minimal busybox is a target-specific build choice upstream, report it to openwrt-devel. "Device has no `hostname`" is a surprising default.
- [ ] Verify on NanoPi R5C and any other rockchip targets whether they have the same stripped build; may be broader than E20C.
- [ ] Once fixed properly, simplify `_common.yaml` to remove the /proc/sys/kernel/hostname write and the /etc/config/system bootstrapping.

## Recipe freshness — cross-cutting

- [ ] Scheduled remote trigger that checks OpenWrt's release feed for new stable releases and reports which recipes are still pinned to older versions. Mirrors the PR #1590 watcher pattern. When a new stable drops, the report lists each stale recipe so a maintainer can re-test on hardware and bump. Keeps the "opinionated, current" intent of GOALS.md from rotting into "opinionated, stale."
- [ ] Consider recording the SHA256 of the resulting image manifest in each recipe after validation so drifts are visible in git history (e.g. `validated_against: "openwrt-25.12.2 rockchip/armv8 rev r32802-f505120278"`). Forces an intentional bump, not a silent one.

## Phase 5 — Community and hardening

- [ ] JSON Schema for recipe validation (asked about in the Phase 1 design discussion). Run via pre-commit or CI; reject malformed or under-specified recipes.
- [ ] `recipes/README.md` becomes a real authoring guide with examples and gotchas (uci-defaults runs before network, etc.).
- [ ] Contribution docs covering the "add a recipe" flow for community contributors.
- [ ] Recipe tests: spin up the stack, build each recipe end-to-end against ASU, verify the resulting image contains the expected packages and that `files/etc/uci-defaults/99-asu-defaults` matches what the recipe rendered. Runs in CI against the committed recipes.
- [ ] Static check that every recipe's declared `arch` matches the target it claims (no silent drift between rockchip/armv8 and `aarch64_generic`).

## Phase 6 — Later enhancements

- [ ] Periodic auto-upgrades via the local ASU server, flagged "save for last" in GOALS.md. Requires deciding: does the probe point at our local ASU (LAN-only, doesn't work when the user takes it elsewhere) or a public one? Probably out of scope for homelab-only deployments.
- [ ] Uplift from `podman compose` + our workaround for macOS resource bumps to a reproducible developer bootstrap script that initializes `podman machine` with the right specs the first time.
- [ ] Consider moving `_common.yaml` overrides into per-environment files so different operators can have different baked-in settings without forking orb-forge.

## Design decisions (locked)

- **Root password**: required, user-entered via the form. No auto-generation, no optionality. Blank submissions are rejected client-side.
- **Orb Deployment Token**: required, user-entered via the form. No defaults, no shared tokens.
- **Free-form uci-defaults textarea**: hidden behind an "Advanced" disclosure, collapsed by default, appends after the recipe's rendered defaults. Not removed entirely because there are always edge cases that don't justify a recipe change.
- **Recipe source of truth**: YAML files in `recipes/`, fetched and parsed at runtime in the browser via vendored `js-yaml`. No build step, no preprocessor.
- **Templating**: Mustache.js, vendored into the fork. Logic-less on purpose — forces recipe authors to keep templates simple.

## Cross-cutting / ongoing

- [ ] Track upstream ASU PR #1590 via the scheduled remote trigger at https://claude.ai/code/scheduled/trig_01QQw8LgQs5KLPTGdhkEQCia. When it merges, follow the action section: switch the `asu/` submodule URL from `dboze/asu` back to `openwrt/asu`, delete the fork, delete the trigger.
- [ ] Revisit whether the `asu/` submodule bundle should eventually include other bounded upstream patches (unlikely, but the door is open as long as we maintain a fork).

## Done

- [x] Scaffolding: MIT license, `firmware-selector/` submodule of dboze fork, GOALS.md, README, CLAUDE.md. (3f06bd3)
- [x] Compose stack with redis + asu-server + asu-worker + selector; same-origin nginx reverse proxy so no CORS. (0171a69)
- [x] Build Orb into images at build time via ASU's custom apk repository support, with stock OpenWrt feeds preserved (`repositories_mode: "append"`). Verified end-to-end for Radxa E20C 25.12.2 with orb 1.4.11 in the manifest. (1781217)
- [x] `asu/` submodule pointing at `dboze/asu` on `orb-patches`, cherry-picking the four commits of upstream PR #1590 until it merges. Compose builds ASU from the submodule. (1781217)
- [x] Nginx re-resolves `asu-server` per request so recreating the ASU container no longer requires a selector restart. (28dd9a5)
- [x] Daily scheduled remote trigger watching openwrt/asu#1590 for merge.
