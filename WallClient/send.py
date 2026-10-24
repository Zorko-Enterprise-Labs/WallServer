"""Send files (or commands) to the wall.

    python send.py photo.jpg                 send to the next free slot
    python send.py report.pdf --slot 2       send to a specific slot
    python send.py a.png b.png c.png         several files, one after another
    python send.py --layout grid             single | split | focus | grid
    python send.py --clear [--slot 2]        clear unpinned slots (or one slot)
    python send.py --pin 1 / --unpin 1
    python send.py --blackout                toggle blackout
"""
import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

try:
    CONFIG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    CONFIG = {}  # not set up yet; the defaults below apply
SERVER = CONFIG.get("server", "http://127.0.0.1:8765").rstrip("/")
TOKEN = CONFIG.get("token", "")
NAME = CONFIG.get("name") or socket.gethostname()


class ProgressFile:
    """File wrapper that lets requests stream it while we draw a console progress bar."""

    def __init__(self, path: Path):
        self.f = open(path, "rb")
        self.total = path.stat().st_size
        self.sent = 0
        self.label = path.name if len(path.name) <= 32 else path.name[:29] + "..."
        self.started = time.monotonic()
        self.last_draw = 0.0

    def __len__(self):
        return self.total

    def read(self, size=-1):
        chunk = self.f.read(size if size and size > 0 else 256 * 1024)
        self.sent += len(chunk)
        now = time.monotonic()
        if now - self.last_draw >= 0.1 or self.sent >= self.total:
            self.last_draw = now
            self.draw()
        return chunk

    def draw(self):
        pct = self.sent / self.total if self.total else 1
        filled = int(pct * 24)
        speed = self.sent / max(time.monotonic() - self.started, 1e-6) / 1_048_576
        sys.stdout.write(f"\r  {self.label:<32} [{'#' * filled}{'.' * (24 - filled)}] {pct:4.0%}  {speed:5.1f} MB/s")
        sys.stdout.flush()

    def close(self):
        self.f.close()


def headers(extra=None):
    h = {"X-Wall-Token": TOKEN, "X-From": quote(NAME)}
    h.update(extra or {})
    return h


def send_file(path: Path, slot: int) -> bool:
    if not path.is_file():
        print(f"  Skipped (not a file): {path}")
        return False
    body = ProgressFile(path)
    try:
        r = requests.post(f"{SERVER}/api/push", data=body, timeout=(5, None),
                          headers=headers({"X-Filename": quote(path.name), "X-Slot": str(slot or ""),
                                           "Content-Type": "application/octet-stream"}))
    finally:
        body.close()
    print()
    if r.status_code != 200:
        print(f"  Failed: {r.status_code} {r.text}")
        return False
    print(f"  On the wall in slot {r.json()['slot']}")
    return True


def send_command(payload: dict) -> bool:
    r = requests.post(f"{SERVER}/api/command", json=payload, headers=headers(), timeout=5)
    if r.status_code != 200:
        print(f"Failed: {r.status_code} {r.text}")
        return False
    print("OK")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Send things to the wall.")
    p.add_argument("files", nargs="*", type=Path)
    p.add_argument("--slot", type=int, default=0)
    p.add_argument("--layout", choices=["single", "split", "focus", "grid"])
    p.add_argument("--clear", action="store_true")
    p.add_argument("--clear-all", action="store_true")
    p.add_argument("--pin", type=int)
    p.add_argument("--unpin", type=int)
    p.add_argument("--blackout", action="store_true")
    p.add_argument("--pause-on-error", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args()

    ok = True
    try:
        if a.layout:
            ok &= send_command({"action": "layout", "layout": a.layout})
        if a.clear:
            ok &= send_command({"action": "clear", "slot": a.slot})
        if a.clear_all:
            ok &= send_command({"action": "clear_all"})
        if a.pin:
            ok &= send_command({"action": "pin", "slot": a.pin})
        if a.unpin:
            ok &= send_command({"action": "unpin", "slot": a.unpin})
        if a.blackout:
            ok &= send_command({"action": "blackout"})
        for i, f in enumerate(a.files):
            # with several files and a fixed slot, only the first one is pinned to that slot
            ok &= send_file(f, a.slot if i == 0 else 0)
        if not any([a.files, a.layout, a.clear, a.clear_all, a.pin, a.unpin, a.blackout]):
            p.print_help()
    except requests.ConnectionError:
        print(f"\nCan't reach the wall server at {SERVER}. Is it running, and is 'server' in config.json right?")
        ok = False

    if not ok and a.pause_on_error:
        input("\nPress Enter to close...")
    elif a.pause_on_error:
        time.sleep(1.2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
