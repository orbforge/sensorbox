#!/usr/bin/env python3
"""Flash a sensorbox image to real hardware and assert that it booted.

Why this exists rather than `sysupgrade`: sysupgrade preserves the existing
partition layout, so it cannot validate changes to that layout, and it needs a
booted OS with working SSH -- exactly what a bad image destroys. This path
drives U-Boot over serial and writes the WHOLE image, partition table
included, so it works from a board whose kernel does not boot at all.

    ./hwtest.py flash --image path/to/openwrt-...-sysupgrade.img
    ./hwtest.py flash --image ... --no-write   # transport only, eMMC untouched
    ./hwtest.py verify                          # assert on the next boot
    ./hwtest.py console                         # interactive

One-time setup (see README.md): setup/grant-serial.sh and setup/grant-tftp.sh.
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time

import yaml

from serial_console import SerialConsole, SerialConsoleError

HERE = os.path.dirname(os.path.abspath(__file__))
SECTOR = 512


def log(msg):
    sys.stderr.write("[hwtest] %s\n" % msg)
    sys.stderr.flush()


def load_target(name):
    with open(os.path.join(HERE, "targets.yaml")) as fh:
        targets = yaml.safe_load(fh)
    if name not in targets:
        sys.exit("unknown target %r (have: %s)" % (name, ", ".join(targets)))
    return targets[name]


class Tftpd:
    """Runs tftpd.py alongside, serving the directory holding the image."""

    def __init__(self, root, port):
        self.root, self.port, self.proc = root, port, None

    def __enter__(self):
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "tftpd.py"),
             "--root", self.root, "--port", str(self.port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(0.5)
        if self.proc.poll() is not None:
            err = self.proc.stderr.read().decode(errors="replace")
            sys.exit("tftpd failed to start: %s" % err.strip())
        log("tftpd serving %s on :%d" % (self.root, self.port))
        return self

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=5)


def console_reboot(con, cfg):
    """Log in over the serial console and run `reboot`.

    Works whenever the DUT still boots, which is the overwhelmingly common
    case, and needs no extra hardware -- so the loop runs unattended. It
    cannot help once an image fails to boot: there is no shell to log into,
    and that is what the `command` method is for.
    """
    con.buffer = b""
    con.send("")
    con.read_for(3)
    text = con.buffer.decode(errors="replace")

    if "login:" in text:
        user = cfg.get("login_user") or "root"
        log("console wants a login; sending user %r" % user)
        con.send(user)
        con.read_for(2)
        if "assword" in con.buffer.decode(errors="replace"):
            password = cfg.get("login_password")
            if not password:
                log("console asked for a password but none is configured")
                return False
            con.send(password)
        con.read_for(3)
    elif "press Enter" in text:
        # OpenWrt's askconsole shim: a second Enter opens the shell.
        con.send("")
        con.read_for(2)

    if not con.send_and_wait("", "#", 8):
        log("no shell prompt on the console")
        return False

    log("issuing reboot over the console")
    con.send("reboot")
    return True


def reset_dut(con, target):
    """Get the DUT back into U-Boot's autoboot window."""
    cfg = target.get("reset") or {}
    method = cfg.get("method", "manual")

    if method == "console_reboot":
        if console_reboot(con, cfg):
            return
        method = cfg.get("fallback", "manual")
        log("console reboot unavailable -- falling back to %r" % method)

    if method == "command":
        cmd = target.get("power_cycle_cmd")
        if not cmd:
            sys.exit("reset method 'command' but no power_cycle_cmd configured")
        log("power-cycling via: %s" % cmd)
        subprocess.run(cmd, shell=True, check=True)
        return

    log("=" * 62)
    log("POWER-CYCLE THE BOARD NOW")
    log("=" * 62)


def assert_boot(logtext, target):
    """Check a captured boot log against the target's assertions."""
    rules = target["boot_assertions"]
    results, ok = [], True
    for pattern in rules.get("required", []):
        hit = pattern in logtext
        ok &= hit
        results.append(("required", pattern, hit))
    for pattern in rules.get("forbidden", []):
        hit = pattern in logtext
        ok &= not hit
        results.append(("forbidden", pattern, not hit))
    return ok, results


def report(results, fresh=None):
    print()
    print("  %-10s %-8s %s" % ("KIND", "RESULT", "PATTERN"))
    print("  " + "-" * 68)
    for kind, pattern, passed in results:
        print("  %-10s %-8s %s" % (kind, "PASS" if passed else "FAIL", pattern))
    if fresh is not None:
        print()
        print("  fresh flash: %s" % ("yes -- overlay was reinitialised" if fresh
                                     else "no -- overlay survived (not a clean write?)"))


def capture_boot(con, target, timeout, echo=False):
    """Read the boot log until every required assertion has appeared.

    `timeout` is a ceiling, not a duration. A passing boot satisfies all the
    assertions in about 30s, so blocking on a 120s ceiling every cycle threw
    away most of the wall clock for no extra information.
    """
    required = target["boot_assertions"].get("required", [])
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        con.read_for(min(2.0, left), echo=echo)
        if all(p in con.buffer.decode(errors="replace") for p in required):
            # Settle briefly so a panic arriving just after the last marker
            # still lands in the log and trips a forbidden assertion.
            con.read_for(2.0, echo=echo)
            return True


def do_flash(args):
    target = load_target(args.target)
    net, fl = target["network"], target["flash"]
    ser = target["serial"]

    image = os.path.abspath(args.image)
    if not os.path.isfile(image):
        sys.exit("no such image: %s" % image)
    size = os.path.getsize(image)
    blocks = (size + SECTOR - 1) // SECTOR
    log("image %s" % os.path.basename(image))
    log("  %d bytes = %d blocks (0x%x)" % (size, blocks, blocks))

    with Tftpd(os.path.dirname(image), net["tftp_port"]) as _tftpd, \
         SerialConsole(ser["port"], ser["baud"], args.log) as con:

        reset_dut(con, target)
        if not con.interrupt_uboot(ser["autoboot_timeout"], echo=args.verbose):
            sys.exit("never saw the autoboot banner -- was the board reset?")
        log("at U-Boot prompt")

        for cmd in ("setenv ipaddr %s" % net["dut_ip"],
                    "setenv netmask %s" % net["netmask"],
                    "setenv serverip %s" % net["host_ip"]):
            con.send(cmd)

        # Verify the env stuck. The console echo drops characters at 1.5 Mbaud,
        # so the echoed command is not evidence -- printenv is.
        con.send_and_wait("printenv ipaddr serverip", "serverip=", 10)
        env = con.buffer.decode(errors="replace")
        if ("ipaddr=%s" % net["dut_ip"]) not in env or \
           ("serverip=%s" % net["host_ip"]) not in env:
            sys.exit("network env did not take:\n%s" % env)
        log("env set: dut=%s server=%s" % (net["dut_ip"], net["host_ip"]))

        log("loading image over TFTP...")
        if not con.send_and_wait(
                "tftpboot %s %s" % (fl["load_addr"], os.path.basename(image)),
                "Bytes transferred", args.tftp_timeout, echo=args.verbose):
            sys.exit("TFTP transfer did not complete (check the direct link)")
        m = re.search(r"Bytes transferred = (\d+)", con.buffer.decode(errors="replace"))
        if not m or int(m.group(1)) != size:
            sys.exit("TFTP size mismatch: U-Boot reported %s, expected %d"
                     % (m.group(1) if m else "nothing", size))
        log("loaded %d bytes into %s" % (size, fl["load_addr"]))

        if args.no_write:
            log("--no-write: stopping before mmc write, eMMC untouched")
            return 0

        con.send_and_wait("mmc dev %d" % fl["mmc_dev"], "is current device", 15)
        log("selected mmc dev %d" % fl["mmc_dev"])

        log("writing to eMMC (this overwrites the partition table)...")
        if not con.send_and_wait(
                "mmc write %s %x %x" % (fl["load_addr"], fl["start_block"], blocks),
                "blocks written: OK", args.write_timeout, echo=args.verbose):
            sys.exit("mmc write did not report success -- board may not boot")
        log("write OK: %d blocks" % blocks)

        log("resetting and capturing the boot...")
        con.buffer = b""
        con.send("reset")
        if capture_boot(con, target, args.boot_timeout, echo=args.verbose):
            log("boot markers all seen")
        else:
            log("boot-timeout ceiling hit before all markers appeared")
        text = con.buffer.decode(errors="replace")

    ok, results = assert_boot(text, target)
    fresh = target["boot_assertions"].get("fresh_flash_hint") in text
    report(results, fresh)
    print("\nRESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def do_verify(args):
    target = load_target(args.target)
    ser = target["serial"]
    with SerialConsole(ser["port"], ser["baud"], args.log) as con:
        reset_dut(con, target)
        log("capturing boot (ceiling %ds)..." % args.boot_timeout)
        capture_boot(con, target, args.boot_timeout, echo=args.verbose)
        text = con.buffer.decode(errors="replace")
    ok, results = assert_boot(text, target)
    report(results)
    print("\nRESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def do_console(args):
    target = load_target(args.target)
    ser = target["serial"]
    with SerialConsole(ser["port"], ser["baud"], args.log) as con:
        con.interactive()
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default="radxa_e20c")
    p.add_argument("--log", help="append the raw serial stream to this file")
    p.add_argument("-v", "--verbose", action="store_true", help="echo serial to stdout")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("flash", help="load an image over TFTP and write it to eMMC")
    f.add_argument("--image", required=True)
    f.add_argument("--no-write", action="store_true",
                   help="stop after the TFTP load; do not touch the eMMC")
    f.add_argument("--tftp-timeout", type=float, default=300)
    f.add_argument("--write-timeout", type=float, default=300)
    f.add_argument("--boot-timeout", type=float, default=120)
    f.set_defaults(func=do_flash)

    v = sub.add_parser("verify", help="capture the next boot and assert on it")
    v.add_argument("--boot-timeout", type=float, default=120)
    v.set_defaults(func=do_verify)

    c = sub.add_parser("console", help="interactive serial console")
    c.set_defaults(func=do_console)

    args = p.parse_args()
    try:
        sys.exit(args.func(args))
    except SerialConsoleError as e:
        sys.exit("error: %s" % e)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
