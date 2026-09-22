#!/usr/bin/env python3
"""Auto-confirm CLO's modal option dialogs so an unattended batch can proceed.

CLO opens modal dialogs for several API calls. While one is up CLO is not
running the bridge's poll loop, so a batch stalls indefinitely. Known cases:

  * ExportOBJ and the Export*WithDialog variants -> an export options dialog
  * ImportFile on a .zprj, when a project is ALREADY open -> "Open Project"
    (Load Type: Open vs Add). This one does NOT appear on a first load, which
    is why it surfaced late.

Identifying them is awkward: the accessibility title is often just "Dialog",
with the real heading drawn inside the window. So a dialog is matched on a
CONTENT SIGNATURE - the set of buttons and checkboxes it exposes - not on its
title alone. Anything unrecognised is reported and left strictly alone;
blind-clicking an overwrite or discard-changes prompt could destroy work.
"""
import re
import subprocess
import sys
import time


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip(), r.returncode


def _list(kind, window=None):
    scope = f'tell window "{window}" to ' if window else ""
    out, rc = osa(f'tell application "System Events" to tell process "CLO" '
                  f'to {scope}get name of every {kind}')
    if rc != 0 or not out:
        return []
    return [x.strip() for x in out.split(",")
            if x.strip() and x.strip() != "missing value"]


def windows():
    return [w for w in _list("window") if w != "CLO Network OnlineAuth"]


# A dialog is safe to confirm when its title matches, or when its checkboxes
# contain one of these signatures. Keep these specific.
TITLE_OK = re.compile(r"^(Import|Export)\s+(OBJ|FBX|GLB|GLTF|Alembic|USD)", re.I)
SIGNATURES = [
    {"name": "Open Project", "need": {"Garment", "Avatar"}, "click": "OK"},
    {"name": "OBJ export options", "need": {"Save Colorways"}, "click": "OK"},
    {"name": "OBJ import options", "need": {"Weld Turned Sewing Lines"}, "click": "OK"},
]


def classify(win):
    if TITLE_OK.match(win):
        return "title:" + win, "OK"
    boxes = set(_list("checkbox", win))
    buttons = set(_list("button", win))
    for sig in SIGNATURES:
        if sig["need"] <= boxes and sig["click"] in buttons:
            return sig["name"], sig["click"]
    return None, None


def main():
    deadline = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 600)
    clicked, ignored = 0, {}
    while time.time() < deadline:
        for w in windows():
            kind, button = classify(w)
            if kind:
                _, rc = osa(f'tell application "System Events" to tell process "CLO" '
                            f'to tell window "{w}" to click button "{button}"')
                if rc == 0:
                    clicked += 1
                    print(f"  [{time.strftime('%H:%M:%S')}] confirmed {kind} "
                          f"(button {button})", flush=True)
                    time.sleep(1.0)
            elif w not in ignored:
                ignored[w] = sorted(_list("checkbox", w))[:8]
                print(f"  [{time.strftime('%H:%M:%S')}] LEFT ALONE: {w!r} "
                      f"checkboxes={ignored[w]}", flush=True)
        time.sleep(0.5)
    print(f"watcher done: {clicked} confirmed; left alone: {sorted(ignored) or 'none'}")


if __name__ == "__main__":
    main()
