#!/usr/bin/env python3
"""Minimal read-only TFTP server (RFC 1350 + RFC 2348 blksize).

Read-only and single-directory on purpose: this exists to feed U-Boot an
image, not to be a general file server. Writes (WRQ) are refused.

  ./tftpd.py --root . --port 69
"""
import argparse
import os
import re
import socket
import struct
import sys
import time

RRQ, WRQ, DATA, ACK, ERROR, OACK = 1, 2, 3, 4, 5, 6

# "<file>@<offset>+<length>" serves that byte range of <file> instead of a
# file on disk. hwtest.py uses it to move an image larger than the DUT's RAM
# in pieces, without materialising gigabytes of temporary chunk files. '@'
# and '+' are safe in a U-Boot tftpboot filename; only ':' is special there
# (it separates serverip from the path).
SLICE = re.compile(r"^(.+)@(\d+)\+(\d+)$")


def log(msg):
    sys.stderr.write("%s\n" % msg)
    sys.stderr.flush()


def send_error(sock, addr, code, msg):
    sock.sendto(struct.pack("!HH", ERROR, code) + msg.encode() + b"\0", addr)


def parse_request(data):
    # opcode, then NUL-separated: filename, mode, then option/value pairs
    parts = data[2:].split(b"\0")
    filename = parts[0].decode("latin-1")
    mode = parts[1].decode("latin-1").lower() if len(parts) > 1 else "octet"
    opts = {}
    rest = [p for p in parts[2:] if p != b""]
    for i in range(0, len(rest) - 1, 2):
        opts[rest[i].decode("latin-1").lower()] = rest[i + 1].decode("latin-1")
    return filename, mode, opts


def refuse(client, code, msg):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_error(s, client, code, msg)
    s.close()


def serve_file(root, filename, mode, opts, client):
    offset, length = 0, None
    m = SLICE.match(filename)
    if m:
        filename, offset, length = m.group(1), int(m.group(2)), int(m.group(3))
    safe = os.path.normpath("/" + filename).lstrip("/")
    path = os.path.join(root, safe)
    if not os.path.isfile(path):
        log("  -> NOT FOUND: %s" % path)
        refuse(client, 1, "File not found")
        return

    total = os.path.getsize(path)
    if length is None:
        length = total
    if offset + length > total:
        log("  -> slice %d+%d runs past the end of %s (%d bytes)" % (offset, length, safe, total))
        refuse(client, 1, "Slice past end of file")
        return
    size = length
    label = safe if not m else "%s[%d:%d]" % (safe, offset, offset + length)
    blksize = 512
    ack_oack = False
    reply_opts = []
    if "blksize" in opts:
        blksize = max(8, min(65464, int(opts["blksize"])))
        reply_opts += [b"blksize", str(blksize).encode()]
        ack_oack = True
    if "tsize" in opts:
        reply_opts += [b"tsize", str(size).encode()]
        ack_oack = True

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(3.0)
    log("  -> %s (%d bytes, blksize=%d) to %s:%d" % (label, size, blksize, client[0], client[1]))

    started = time.monotonic()
    try:
        if ack_oack:
            pkt = struct.pack("!H", OACK) + b"\0".join(reply_opts) + b"\0"
            if not await_ack(sock, pkt, client, 0):
                return

        with open(path, "rb") as fh:
            fh.seek(offset)
            remaining = size
            block = 1
            while True:
                # A transfer whose size is an exact multiple of blksize still
                # needs a final empty DATA packet; min(blksize, 0) gives it.
                chunk = fh.read(min(blksize, remaining))
                remaining -= len(chunk)
                pkt = struct.pack("!HH", DATA, block & 0xFFFF) + chunk
                if not await_ack(sock, pkt, client, block & 0xFFFF):
                    log("  -> ABORTED at block %d" % block)
                    return
                if len(chunk) < blksize:
                    break
                block += 1
        dur = time.monotonic() - started
        rate = (size / dur / 1024) if dur > 0 else 0
        log("  -> COMPLETE %d bytes in %.1fs (%.0f KiB/s)" % (size, dur, rate))
    finally:
        sock.close()


def await_ack(sock, pkt, client, expect, retries=5):
    """Send pkt, wait for ACK of `expect`. Returns False if the peer gave up."""
    for _ in range(retries):
        sock.sendto(pkt, client)
        try:
            resp, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        if addr[0] != client[0] or len(resp) < 4:
            continue
        op, blk = struct.unpack("!HH", resp[:4])
        if op == ERROR:
            log("  -> client error: %s" % resp[4:].rstrip(b"\0").decode("latin-1", "replace"))
            return False
        if op == ACK and blk == expect:
            return True
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--port", type=int, default=69)
    p.add_argument("--bind", default="0.0.0.0")
    a = p.parse_args()

    root = os.path.abspath(a.root)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((a.bind, a.port))
    except PermissionError:
        sys.exit("cannot bind UDP %d without privileges (see setup notes)" % a.port)
    log("tftpd: serving %s on %s:%d (read-only)" % (root, a.bind, a.port))

    while True:
        data, client = sock.recvfrom(65536)
        if len(data) < 2:
            continue
        op = struct.unpack("!H", data[:2])[0]
        if op == WRQ:
            log("WRQ from %s:%d refused (read-only)" % client)
            send_error(sock, client, 2, "Server is read-only")
            continue
        if op != RRQ:
            continue
        filename, mode, opts = parse_request(data)
        log("RRQ %s:%d  file=%r mode=%s opts=%s" % (client[0], client[1], filename, mode, opts))
        pid = os.fork()
        if pid == 0:
            sock.close()
            serve_file(root, filename, mode, opts, client)
            os._exit(0)
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break


if __name__ == "__main__":
    main()
