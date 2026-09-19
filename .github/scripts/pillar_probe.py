#!/usr/bin/env python3
"""Probe a REFInet Pillar over Gopher, using nothing but the standard library.

The health monitor and the deploy workflow both speak to a running Pillar to
decide whether it is alive. They used to do it with `nc -q2`, which is a
netcat-openbsd flag: the health job installed that package, the deploy job
did not, so the deploy health check depended on whichever netcat the runner
image happened to ship. This script removes the guesswork, and the workflows
that call it need no dependencies installed at all.

Usage:
    pillar_probe.py online   <host> <port> [--retries N] [--delay S]
    pillar_probe.py menu     <host> <port> [--lines N]
    pillar_probe.py services <host> <port>

`online` exits 0 when the Pillar answers and its root menu names REFInet, and
1 when it does not. An unreachable host is an answer, not a crash, so nothing
here raises on a network error.
"""

import argparse
import json
import socket
import sys
import time

DEFAULT_TIMEOUT = 5.0
MAX_RESPONSE = 256 * 1024
SIGNATURE_MARKER = "---BEGIN REFINET SIGNATURE---"


def fetch(host, port, selector="", timeout=DEFAULT_TIMEOUT):
    """Send a Gopher selector and return the raw response bytes."""
    chunks, total = [], 0
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.sendall(selector.encode("utf-8") + b"\r\n")
        sock.settimeout(timeout)
        while total < MAX_RESPONSE:
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks)


def try_fetch(host, port, selector="", timeout=DEFAULT_TIMEOUT):
    """fetch(), but a network failure returns None instead of raising."""
    try:
        return fetch(host, port, selector, timeout)
    except (OSError, ValueError):
        return None


def body_of(raw):
    """Return a response's payload, without its envelope.

    A Pillar appends a signature block to every answer, and a Gopher text
    response ends with a lone "." on its own line. Both sit outside the
    payload; neither is verified here, because checking an Ed25519 signature
    would mean installing a dependency into a workflow that has none.
    """
    text = raw.decode("utf-8", errors="replace")
    text = text.split(SIGNATURE_MARKER, 1)[0]
    text = text.rstrip()
    if text.endswith("."):
        text = text[:-1]
    return text.strip()


def cmd_online(args):
    """Exit 0 if the Pillar answers with a REFInet root menu."""
    for attempt in range(1, args.retries + 1):
        body = try_fetch(args.host, args.port)
        if body is not None and b"refinet" in body.lower():
            print("online")
            return 0
        if attempt < args.retries:
            print(
                "attempt %d/%d: no answer from %s:%s yet"
                % (attempt, args.retries, args.host, args.port),
                file=sys.stderr,
            )
            time.sleep(args.delay)
    print("offline")
    return 1


def cmd_menu(args):
    body = try_fetch(args.host, args.port)
    if body is None:
        print("No answer from %s:%s" % (args.host, args.port), file=sys.stderr)
        return 1
    for line in body_of(body).splitlines()[: args.lines]:
        print(line)
    return 0


def cmd_services(args):
    body = try_fetch(args.host, args.port, "/health/services")
    if body is None:
        print("No answer from %s:%s" % (args.host, args.port), file=sys.stderr)
        return 1
    try:
        data = json.loads(body_of(body))
    except json.JSONDecodeError as exc:
        print("Unparseable /health/services response: %s" % exc, file=sys.stderr)
        return 1
    available = sum(1 for service in data if service.get("available"))
    print("Services: %d/%d available" % (available, len(data)))
    for service in data:
        mark = "✓" if service.get("available") else "○"
        print("  %s %s" % (mark, service.get("name", "?")))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, handler, **kwargs):
        sp = sub.add_parser(name, **kwargs)
        sp.add_argument("host")
        sp.add_argument("port")
        sp.set_defaults(handler=handler)
        return sp

    p_online = add("online", cmd_online, help="Exit 0 when the Pillar answers")
    p_online.add_argument("--retries", type=int, default=1)
    p_online.add_argument("--delay", type=float, default=10.0)

    p_menu = add("menu", cmd_menu, help="Print the root menu")
    p_menu.add_argument("--lines", type=int, default=20)

    add("services", cmd_services, help="Summarise /health/services")

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
