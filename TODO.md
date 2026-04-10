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
- [ ] End-to-end test: build an E20C image via the browser with a real Orb token, flash, verify the device boots, bridges both ethernet ports, pulls DHCP on whichever port is plugged in, links to the Orb account automatically, and has auto-updates enabled.

## Phase 2 — Second device + Wi-Fi capability

- [ ] `recipes/nanopi_r5c.yaml`. This is the Wi-Fi capable device from GOALS.md.
- [ ] Figure out the BE200 driver story — it's mentioned as the hard example in GOALS.md. Check whether there's an OpenWrt package or if it needs buildroot work.
- [ ] Exercise Wi-Fi form fields end-to-end: SSID, password, encryption (psk2 default), band policy (auto / 2.4 / 5 / 6 GHz — GOALS.md calls out each).
- [ ] Wi-Fi `uci` commands in the recipe's `defaults` template, with Mustache vars for user-provided values.
- [ ] Network defaults from GOALS.md: Wi-Fi acts as client, no DHCP server, not pinned to a specific band unless the form says otherwise.

## Phase 3 — Custom ImageBuilder pipeline (NanoPi Zero2 unblocker)

- [ ] `openwrt-builder/` directory in orb-forge: holds patches, DTS, profile snippets, and a reproducible build script (`build.sh` or `Dockerfile.builder`).
- [ ] Populate with the NanoPi Zero2 material referenced in https://github.com/openwrt/openwrt/pull/22707 — the branch in `dboze/openwrt` is the source.
- [ ] `imagebuilder-host` service in compose: nginx sidecar serving the produced ImageBuilder tarballs so ASU can pull from `http://imagebuilder-host/...` instead of `downloads.openwrt.org`.
- [ ] ASU configuration path (env or branches.yaml override) that routes specific (version, target) combinations to the local sidecar.
- [ ] `recipes/friendlyarm_nanopi-zero2.yaml` pinning to the custom ImageBuilder version.
- [ ] CI job (GitHub Actions?) that rebuilds the custom ImageBuilder on each update to the patches or DTS.
- [ ] When PR #22707 merges upstream, drop the custom path for this device and fall back to stock ImageBuilder.

## Phase 4 — Community and hardening

- [ ] JSON Schema for recipe validation (asked about in the Phase 1 design discussion). Run via pre-commit or CI; reject malformed or under-specified recipes.
- [ ] `recipes/README.md` becomes a real authoring guide with examples and gotchas (uci-defaults runs before network, etc.).
- [ ] Contribution docs covering the "add a recipe" flow for community contributors.
- [ ] Recipe tests: spin up the stack, build each recipe end-to-end against ASU, verify the resulting image contains the expected packages and that `files/etc/uci-defaults/99-asu-defaults` matches what the recipe rendered. Runs in CI against the committed recipes.
- [ ] Static check that every recipe's declared `arch` matches the target it claims (no silent drift between rockchip/armv8 and `aarch64_generic`).

## Phase 5 — Later enhancements

- [ ] Periodic auto-upgrades via the local ASU server, flagged "save for last" in GOALS.md. Requires deciding: does the probe point at our local ASU (LAN-only, doesn't work when the user takes it elsewhere) or a public one? Probably out of scope for homelab-only deployments.
- [ ] Uplift from `podman compose` + our workaround for macOS resource bumps to a reproducible developer bootstrap script that initializes `podman machine` with the right specs the first time.
- [ ] Consider moving `_common.yaml` overrides into per-environment files so different operators can have different baked-in settings without forking orb-forge.

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
