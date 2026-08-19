#!/usr/bin/env python3
"""Serial console primitive for the hwtest harness.

Dependency-free on purpose: pyserial is not installed on the bench host and
neither are picocom/minicom/tio, so this drives termios directly. Usable as a
library (SerialConsole) or standalone:

    ./serial_console.py --port /dev/ttyUSB0 --baud 1500000
    ./serial_console.py --interrupt-uboot --send "printenv" --capture 20

Hard-won constraints, all of which cost real debugging time:

  * Only ONE session may hold the port at a time. Two concurrent readers
    steal each other's bytes and the second one silently sees nothing.
  * U-Boot's network loop drains stdin to poll for Ctrl-C, so anything sent
    while `tftpboot` runs is eaten. Only send at an idle prompt.
  * Serial echo drops characters at 1.5 Mbaud. Never parse the echoed
    command back -- assert on state with `printenv` instead.
"""
import argparse
import errno
import fcntl
import os
import select
import struct
import sys
import termios
import time
import tty

QUIT_KEY = 0x1D  # Ctrl-]

TIOCMGET, TIOCMSET = 0x5415, 0x5418
TIOCM_DTR, TIOCM_RTS = 0x002, 0x004


class SerialConsoleError(Exception):
    pass


class SerialConsole:
    """Raw 8N1 serial port with no flow control."""

    def __init__(self, port="/dev/ttyUSB0", baud=1500000, log_path=None):
        self.port = port
        self.baud = baud
        self.fd = None
        self.log = open(log_path, "ab", buffering=0) if log_path else None
        self.buffer = b""

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def open(self):
        speed = getattr(termios, "B%d" % self.baud, None)
        if speed is None:
            raise SerialConsoleError("baud %d unsupported by termios" % self.baud)
        try:
            self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except PermissionError:
            raise SerialConsoleError(
                "permission denied on %s -- run hwtest/setup/grant-serial.sh once"
                % self.port)
        except OSError as e:
            raise SerialConsoleError("cannot open %s: %s" % (self.port, e.strerror))
        os.set_blocking(self.fd, True)
        cc = termios.tcgetattr(self.fd)[6]
        cc[termios.VMIN], cc[termios.VTIME] = 1, 0
        termios.tcsetattr(self.fd, termios.TCSANOW, [
            termios.IGNPAR, 0,
            termios.CS8 | termios.CREAD | termios.CLOCAL,
            0, speed, speed, cc,
        ])
        termios.tcflush(self.fd, termios.TCIFLUSH)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.log:
            self.log.close()
            self.log = None

    # --- modem control lines -------------------------------------------------
    # DTR/RTS are software-settable outputs. Wired through a MOSFET or an
    # opto-isolated relay they give power control with no extra USB device --
    # the same trick ESP32 boards use for auto-reset.

    def _modem_bits(self):
        return struct.unpack("I", fcntl.ioctl(self.fd, TIOCMGET, struct.pack("I", 0)))[0]

    def set_line(self, name, asserted):
        bit = {"dtr": TIOCM_DTR, "rts": TIOCM_RTS}[name.lower()]
        bits = self._modem_bits()
        bits = (bits | bit) if asserted else (bits & ~bit)
        fcntl.ioctl(self.fd, TIOCMSET, struct.pack("I", bits))

    def send_break(self):
        """Assert a serial BREAK condition.

        On a Linux serial console a BREAK is the magic-SysRq prefix, so
        BREAK followed by a command byte reaches the kernel directly.
        """
        termios.tcsendbreak(self.fd, 0)

    def sysrq(self, key):
        """Issue a magic SysRq command (e.g. "b" to reboot immediately)."""
        self.send_break()
        time.sleep(0.05)
        os.write(self.fd, key.encode())

    # --- io ------------------------------------------------------------------

    def _record(self, data, echo):
        self.buffer += data
        self.buffer = self.buffer[-1048576:]
        if self.log:
            self.log.write(data)
        if echo:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

    def read_for(self, seconds, echo=False, until=None):
        """Drain the port for `seconds`. Returns early if `until` is seen."""
        end = time.monotonic() + seconds
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            try:
                ready, _, _ = select.select([self.fd], [], [], min(remaining, 0.25))
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                raise
            if self.fd in ready:
                data = os.read(self.fd, 4096)
                if data:
                    self._record(data, echo)
                    if until and until.encode() in self.buffer:
                        return True

    def send(self, command, settle=0.3):
        """Write one line. Caller must ensure the prompt is idle first."""
        os.write(self.fd, command.encode() + b"\r")
        time.sleep(settle)

    def send_and_wait(self, command, until, timeout, echo=False):
        """Send a command and wait for `until`. Returns True if it appeared."""
        self.buffer = b""
        self.send(command)
        return self.read_for(timeout, echo=echo, until=until)

    def interrupt_uboot(self, timeout, quiesce=0.6, echo=False):
        """Tap CR through the autoboot window to stop at the U-Boot prompt.

        Stops tapping the moment the banner appears: every extra CR echoes a
        fresh prompt, which would keep the console 'busy' forever and we would
        never detect that it had gone quiet.
        """
        deadline = time.monotonic() + timeout
        seen_banner = False
        last_rx = time.monotonic()
        self.buffer = b""

        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [], 0.05)
            if self.fd in ready:
                data = os.read(self.fd, 4096)
                if data:
                    self._record(data, echo)
                    last_rx = time.monotonic()
                    if b"stop autoboot" in self.buffer:
                        seen_banner = True
            if seen_banner:
                if (time.monotonic() - last_rx) > quiesce:
                    return True
            else:
                os.write(self.fd, b"\r")
        return False

    def interactive(self):
        saved = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        sys.stdout.buffer.write(
            ("[%s @ %d -- Ctrl-] to quit]\r\n" % (self.port, self.baud)).encode())
        sys.stdout.buffer.flush()
        try:
            while True:
                ready, _, _ = select.select([self.fd, sys.stdin.fileno()], [], [])
                if self.fd in ready:
                    data = os.read(self.fd, 4096)
                    if not data:
                        break
                    self._record(data, echo=True)
                if sys.stdin.fileno() in ready:
                    key = os.read(sys.stdin.fileno(), 1024)
                    if not key or QUIT_KEY in key:
                        break
                    os.write(self.fd, key)
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, saved)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=1500000)
    p.add_argument("--log")
    p.add_argument("--interrupt-uboot", action="store_true")
    p.add_argument("--interrupt-timeout", type=float, default=180.0)
    p.add_argument("--send", action="append", default=[])
    p.add_argument("--capture", type=float, help="read for N seconds then exit")
    a = p.parse_args()

    try:
        with SerialConsole(a.port, a.baud, a.log) as con:
            if a.interrupt_uboot:
                sys.stderr.write("[waiting for autoboot window -- power-cycle the board]\n")
                ok = con.interrupt_uboot(a.interrupt_timeout, echo=True)
                sys.stderr.write("\n[%s]\n" % ("at U-Boot prompt" if ok
                                               else "WARNING: never saw the autoboot banner"))
            for cmd in a.send:
                sys.stderr.write("[send] %s\n" % cmd)
                con.send(cmd)
            if a.capture is not None:
                con.read_for(a.capture, echo=True)
            elif not a.send and not a.interrupt_uboot:
                con.interactive()
    except SerialConsoleError as e:
        sys.exit("error: %s" % e)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
