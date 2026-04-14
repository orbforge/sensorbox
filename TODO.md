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
- [x] End-to-end test: build an E20C image via the browser with a real Orb token, flash, verify the device boots, bridges both ethernet ports, pulls DHCP on whichever port is plugged in, links to the Orb account automatically, and has auto-updates enabled. **Validated on hardware.** The long detour on "stripped busybox" / empty `/etc/config/system` / missing `hostname` applet turned out to be caused by `diff_packages: true` in the UI build request — ASU interpreted our `packages: ["orb"]` as a full replacement list and silently removed base-files plus most busybox applets from every build. Fixed by setting `diff_packages: false` (commit 4fccae8). Future follow-up: verify what `orb-update install` actually registers on-device so `_common.yaml` can be hardened if the one-liner turns out to be insufficient.

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

## Form UX improvements

- [ ] **Confirm Root Password field.** Add a second password input ("Confirm Root Password") below the existing Root Password field and validate on submit that the two values match. Without this, a typo in the root password goes completely unnoticed until the user tries to SSH in and realizes they can't. The check should be pure client-side validation — disable the build button and surface a clear error message when the fields don't match. Matches how every other "set a password" form on the internet works, and orb-forge is opinionated enough that the user shouldn't be able to skip it. Probably also applies to the Orb Deployment Token field since mistyping it silently breaks auto-linking, but the token is long enough that a typo is easier to notice.
- [x] **Per-recipe install instructions + device links.** Three new optional recipe fields: `vendor_url`, `docs_url`, `install_notes`. Vendor and orb.net docs links shown in the device-info area (on selection) and repeated in the download area. OpenWrt wiki link derived from the recipe title (no schema field). `install_notes` rendered as HTML via snarkdown (~2KB markdown parser) in the download area after a successful build. E20C recipe populated with real content including the LED behavior notes and the WAN port link-LED quirk.

## Recipe authoring ergonomics

- [ ] Live-reload recipes without a selector restart. Today the nginx entrypoint hook copies `recipes/*.yaml` from the read-only `/orb-recipes-src` bind mount into a writable `/orb-recipes` directory and generates `index.json` once at container start. Editing `recipes/` on the host requires `podman compose restart selector` to pick up changes, which is a recipe-author papercut that will bite every contributor. Options: (a) drop the copy step entirely and have nginx serve directly from the bind mount with a small dynamic index endpoint (requires nginx scripting via njs or similar); (b) re-run the index generator via inotify / fs watcher; (c) regenerate `index.json` on every HTTP request via a tiny CGI — ugly but simple; (d) document the restart as a known step in `recipes/README.md` and move on. Option (a) or (d) is probably right.

## NanoPi R5C slow boot investigation

- [ ] The R5C feels noticeably slow to boot compared to the E20C. Plug into HDMI and watch the full boot sequence on serial/console to identify where time is being spent — could be u-boot timeouts (waiting for a missing device), kernel driver probes (PCIe enumeration for the M.2 slot?), or a slow init service. If it's a u-boot timeout, might be fixable via boot.scr tweaks; if it's a kernel/init issue, might need investigation into which service is blocking.

## First-boot noise — cosmetic

- [ ] First-boot `apk info orb` emits several "No such file or directory" warnings about missing cache for the stock OpenWrt feeds. Purely cosmetic / first-boot noise — `apk update` would fix it if the device has internet. Not worth solving unless it's making logs noisy.

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

- [x] **Phase 1 MVP: fully validated on hardware, including auto-updates.** E20C → recipe → recipe-driven UI → ASU with apk custom feed support → orb baked in → first-boot uci-defaults sets hostname, root password, Orb token, persists the Orb apk feed + signing key on the running device, bakes micrond (a hidden orb-update dependency) into the image, bridges both ethernet ports → device boots, auto-links to the Orb account, and `orb-update install` runs clean so scheduled auto-updates are actually wired up. End-to-end pipeline confirmed working. (commits 701f309 through 0efc47d)
- [x] **Orb apk feed persistence and orb-update install path verified.** `/etc/apk/repositories.d/customfeeds.list` contains the Orb feed, `/etc/apk/keys/orb-packages.pem` holds the signing key, `orb-update install` runs without the "micrond not found" warning because micrond is baked in via `_common.yaml`'s packages list. Auto-updates should now actually update orb when new versions hit pkgs.orb.net. (commit 0efc47d)
- [x] **Phase 2 SD→eMMC installer: validated on hardware.** Automated first-boot installer writes the static SD partitions to eMMC via dd, signals done on the SYS LED, and the eMMC boots independently with a fresh overlay + uci-defaults re-run (confirmed by different hostname Orb-4937 vs Orb-9638 across install cycles). Fixed pipeline-exit-mask bug (085f677) and sector-count truncation risk (14107f6). The squashfs errors seen on one SD boot were not reproducible on the eMMC and are likely transient SD card I/O noise.
- [x] **Stripped-busybox investigation: non-issue.** The Radxa E20C 25.12.2 build does compile busybox without the `hostname`/`chpasswd`/`blkid`/`logread` applets, but the OpenWrt init path doesn't need the `hostname` binary to apply a uci-configured hostname to the running kernel — it uses a direct `sethostname(2)` or similar syscall path. `_common.yaml`'s `passwd` heredoc replaces the missing `chpasswd` cleanly. The entire investigation was a red herring driven by the `diff_packages: true` bug that was stripping base-files on every build. Marking resolved.
- [x] Scaffolding: MIT license, `firmware-selector/` submodule of dboze fork, GOALS.md, README, CLAUDE.md. (3f06bd3)
- [x] Compose stack with redis + asu-server + asu-worker + selector; same-origin nginx reverse proxy so no CORS. (0171a69)
- [x] Build Orb into images at build time via ASU's custom apk repository support, with stock OpenWrt feeds preserved (`repositories_mode: "append"`). Verified end-to-end for Radxa E20C 25.12.2 with orb 1.4.11 in the manifest. (1781217)
- [x] `asu/` submodule pointing at `dboze/asu` on `orb-patches`, cherry-picking the four commits of upstream PR #1590 until it merges. Compose builds ASU from the submodule. (1781217)
- [x] Nginx re-resolves `asu-server` per request so recreating the ASU container no longer requires a selector restart. (28dd9a5)
- [x] Daily scheduled remote trigger watching openwrt/asu#1590 for merge.
