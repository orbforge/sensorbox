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

To catch U-Boot's ~2 s autoboot window the board has to be reset. `targets.yaml`
picks how, via `reset.method`:

- **`console_reboot`** (default) — log in on the serial console and run
  `reboot`. No extra hardware, no human, so the loop runs unattended. This is
  what you want almost always. Set `login_user`/`login_password` to match the
  image: a selector-built one sets `ttylogin` and a root password through
  uci-defaults, while an image from `build.py` has no defaults and drops
  straight to a root shell.
- **`command`** — run `power_cycle_cmd`. The only method that recovers a board
  whose kernel no longer boots, since there is then no shell to log into.
- **`manual`** — print a notice and wait for a person. Used as the `fallback`.

### Note for the E20C specifically

It has **no UART header**; its debug USB-C port is an onboard USB-serial
bridge. So the common trick of driving a relay from the adapter's DTR/RTS
lines is *not* available — those pins are inside the board. Power switching
must be external and independent of the serial path: a LAN smart plug or a
USB relay module in the supply line, wired into `power_cycle_cmd`.

`SerialConsole.set_line()` can still toggle DTR/RTS for boards that *do*
expose them via an external adapter.

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
