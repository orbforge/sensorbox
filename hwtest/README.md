# hwtest — flashing and validating sensorbox images on real hardware

Drives a bench device over its serial console, writes a full image to its
internal storage over TFTP, and asserts that the result boots correctly.

## Why not `sysupgrade`

`sysupgrade` preserves the existing partition layout and needs a booted OS
with working SSH. That makes it unsuitable here for two reasons:

- it cannot validate changes *to* the partition layout, because it bypasses
  the code path being changed;
- its recovery path depends on the very thing a bad image destroys.

This harness talks to U-Boot instead and writes the whole image, partition
table included, so it works even on a board whose kernel does not boot.

## One-time setup

```sh
sudo hwtest/setup/grant-serial.sh   # udev rule -> console without sudo
sudo hwtest/setup/grant-tftp.sh     # redirect UDP/69 -> 6969, unprivileged tftpd
```

Neither is needed again, and nothing in normal operation requires `sudo`.
`grant-tftp.sh --undo` removes the firewall rule.

### Wiring

- **Serial**: USB-serial adapter to the DUT's debug port.
- **Ethernet**: a USB-ethernet dongle wired **directly** to the DUT, host on
  `10.0.0.1/24`. Do not route this through your LAN — U-Boot's ARP for a
  host on wifi does not resolve, and a direct link also keeps the addresses
  stable with no DHCP to drift.
- On the E20C the cable must be in the **LAN port**: that is
  `ethernet@ffbe0000`, U-Boot's only network device. The second port is a
  PCIe Realtek that U-Boot cannot see.

Set the host address once, and it persists:

```sh
nmcli con add type ethernet ifname <iface> con-name sensorbox-lab \
      ipv4.method manual ipv4.addresses 10.0.0.1/24 ipv6.method disabled
```

## Usage

```sh
./hwtest.py flash --image ../public/store/<hash>/openwrt-...-sysupgrade.img
./hwtest.py flash --image ... --no-write   # transport only, storage untouched
./hwtest.py verify                          # assert on the next boot
./hwtest.py console                         # interactive console
```

Images must be **decompressed** (`gzip -dc x.img.gz > x.img`).

`--no-write` is worth using whenever you change the wiring or the network:
it exercises everything up to and including the TFTP load, then stops
without touching the device's storage.

Exit status is 0 on pass, 1 on assertion failure — so this drops into CI or
a loop unchanged.

## Building what the web form builds

`build.py --form values.yaml` produces exactly what the UI produces, including
uci-defaults, so form-driven features are testable end to end: root password,
Wi-Fi credentials and band policy, `ORB_DEPLOYMENT_TOKEN`, `ttylogin`, the
eMMC installer block, and the option-gated template sections.

The templating is **not** re-implemented. `render_defaults.mjs` imports the
selector's own `mergedPackages()` and `assembleDefaults()` and runs them under
Node against the same vendored Mustache, so the harness cannot drift from the
UI. Change a recipe template and this follows automatically.

```sh
./build.py --recipe radxa_e20c --form ../path/to/values.yaml
```

The form file mirrors what the UI collects:

```yaml
formValues:
  root_password: "..."
  orb_token: "..."
  wifi_ssid: "..."          # omit on ethernet-only boards
  wifi_password: "..."
  install_to_emmc: true
  telemetry_enabled: false
  tailscale_enabled: false
selectedOptions: {}          # e.g. {wifi_module: intel_be200}
extraDefaults: |
  # appended verbatim, like the UI's extra-defaults box
```

Values the UI derives rather than asks for are filled in automatically:
`orb_apk_key` from the recipe's first `repository_keys` entry, and the
`install_*` values from the recipe's `install` block when `install_to_emmc`
is set.

**Without `--form`, no defaults are sent at all.** That yields an unhardened
image — no `ttylogin`, no root password, so its serial console opens a root
shell. Fine for validating that a build and boot work, wrong for anything
that depends on the credential-injection path.

Two limits to know: ASU needs `ALLOW_DEFAULTS=1` in its env (already set in
`.env.example`) or it rejects `defaults` outright, and it caps them at
`max_defaults_length`, 20480 bytes by default. A realistic E20C form with the
eMMC installer enabled renders about 15.7 KB, so turning on several more
options can approach that ceiling.

**The form file holds real secrets** — a live deployment token and passwords.
Keep it outside the repo; `hwtest/*.form.yaml` is gitignored as a guard.

## What gets asserted

Configured per target in `targets.yaml`. For the E20C the load-bearing one is
`switching to ext4 overlay`: 25.12.0 on this target silently fell back to a
tmpfs overlay and lost persistence across reboots, and that class of
regression is the reason this harness exists. A `Kernel panic`, a failed
root mount, or a TFTP retry storm all fail the run.

After a genuine write the log also shows `has not been formatted yet` — the
overlay being reinitialised is how you know the flash actually replaced what
was there, rather than the old system booting again.

## Getting the board back into U-Boot

To catch U-Boot's ~2 s autoboot window the board has to be reset.
`reset.methods` in `targets.yaml` lists the ways to try, in order. They
degrade in how much of the DUT has to still be working:

| method | needs | recovers a board that… |
|---|---|---|
| `sysrq_reboot` | a live kernel | has wedged userspace |
| `console_reboot` | working userspace | boots normally |
| `command` | external power switching | does not boot at all |
| `manual` | a person | anything |

**`sysrq_reboot` is the default.** It sends a serial BREAK followed by `b`,
which is magic SysRq's "reboot immediately". Because SysRq is handled in
kernel interrupt context it fires even when userspace is hung, and it needs
no login and no password at all. It requires `/proc/sys/kernel/sysrq` to be
non-zero on the DUT — it is, on OpenWrt here.

The trade-off: SysRq resets without syncing filesystems, so it can leave the
overlay dirty. That is fine when the next step is a full reflash, and it is
arguably a more faithful stand-in for a power cycle than a clean shutdown.

`console_reboot` sits behind it for the case where SysRq is disabled. Fill in
`login_user`/`login_password` to match the image: a selector-built one sets
`ttylogin` and a root password via uci-defaults, while an image from
`build.py` has no defaults and drops straight to a root shell.

`reboot_marker` is the string that proves a cold restart happened. It is the
DDR init banner rather than the U-Boot banner on purpose — the autoboot
prompt follows the U-Boot banner within milliseconds, so syncing on that
would miss the window entirely.

### Note for the E20C specifically

It has **no UART header**; its debug USB-C port is an onboard USB-serial
bridge. So the usual trick of driving a relay from the adapter's DTR/RTS
lines is *not* available — those pins are inside the board. Power switching
has to be external and independent of the serial path: a LAN smart plug or a
USB relay module in the supply line, wired into `power_cycle_cmd`.

`SerialConsole.set_line()` can still toggle DTR/RTS for boards that *do*
expose them through an external adapter.

## Constraints worth knowing

These all cost real debugging time:

- **One serial session at a time.** Two readers steal each other's bytes and
  the second sees nothing.
- **U-Boot eats stdin during `tftpboot`.** Its network loop drains input to
  poll for Ctrl-C, so anything sent mid-transfer vanishes. Only send at an
  idle prompt.
- **Serial echo drops characters at 1.5 Mbaud.** Never parse an echoed
  command; assert on state with `printenv`.
- **Never run `crc32` over a whole image.** It wedges U-Boot and forces a
  physical power cycle. Verify after boot, from Linux, instead.
