#!/usr/bin/env python3
"""Exercise the discovered MCP tools against a copy of a real CLO garment.

Run with the bridge active and confirm modal dialogs manually or with the
macOS dialog watcher. The harness saves the current scene to a scratch backup
before replacing it, restores that backup, then explicitly stops the bridge.
Saving/restoring changes CLO's active project path to the backup. A crash or
blocked native call can prevent restoration; the backup is retained on disk.
"""
import json
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from live_validation import validate_result
from clo3d_mcp.ipc import comm_directory

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER_BIN = REPO / ".venv" / ("Scripts/clo3d-mcp.exe" if os.name == "nt" else "bin/clo3d-mcp")
COMM = comm_directory()
ASSETS = pathlib.Path.home() / "Documents" / "CLO" / "CLO Assets"


class IndeterminateCommand(RuntimeError):
    """The bridge may still be executing a call; do not queue more mutations."""


class Server:
    def __init__(self):
        self.p = subprocess.Popen(
            [str(SERVER_BIN)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
            env=dict(os.environ, CLO3D_MCP_DIR=COMM))
        self.q, self.n = queue.Queue(), 0
        threading.Thread(target=lambda: [self.q.put(l) for l in self.p.stdout], daemon=True).start()
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "live-test", "version": "1"}})
        self._notify("notifications/initialized")

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _notify(self, method):
        self._send({"jsonrpc": "2.0", "method": method})

    def _rpc(self, method, params, timeout=240):
        self.n += 1
        mid = self.n
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            m = json.loads(self.q.get(timeout=max(.01, deadline - time.monotonic())).strip())
            if m.get("id") == mid:
                return m

    def call(self, name, args=None, timeout=240):
        r = self._rpc("tools/call", {"name": name, "arguments": args or {}}, timeout)
        if "error" in r:
            return False, r["error"].get("message", "rpc error")
        res = r["result"]
        text = "".join(c.get("text", "") for c in res.get("content", []))
        if res.get("isError"):
            if any(marker in text for marker in (
                "Timed out waiting for CLO3D", "outcome is unknown", "check its outcome"
            )):
                raise IndeterminateCommand(text.strip())
            return False, text.strip()
        try:
            payload = json.loads(text)
            validate_result(name, payload, args or {})
            return True, payload
        except Exception as exc:
            return False, f"Validation failed: {exc}; response: {text[:200]}"

    def close(self):
        self.p.terminate()
        try:
            self.p.wait(5)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()


def first_asset(subdir, ext):
    d = ASSETS / subdir
    if not d.is_dir():
        return None
    for p in sorted(d.rglob(f"*{ext}")):
        return str(p)
    return None


def _release_bridge():
    """Request stop between commands; cannot interrupt a blocked native call."""
    try:
        open(os.path.join(COMM, "stop"), "w").close()
    except OSError:
        pass


ACTIVE = {}


def exercise():
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = pathlib.Path(positional[0] if positional else REPO / "test.zprj")
    if not src.is_file():
        print(f"garment not found: {src}")
        return 2
    if not SERVER_BIN.exists():
        print(f"server not installed: {SERVER_BIN}")
        return 2

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="clo3d-live-"))
    garment = scratch / "garment.zprj"
    shutil.copy2(src, garment)
    out = scratch / "out"
    out.mkdir()
    print(f"garment copy : {garment}")
    print(f"output dir   : {out}\n")

    srv = Server()
    ACTIVE["server"] = srv
    results = []
    state = {}
    box = {}

    def run(label, tool, args=None, timeout=240, note=""):
        count_checks = {
            "create_pattern": ("get_pattern_count", 1),
            "copy_pattern": ("get_pattern_count", 1),
            "delete_pattern": ("get_pattern_count", -1),
            "add_fabric": ("get_fabric_count", 1),
            "import_fabric": ("get_fabric_count", 1),
            "delete_fabric": ("get_fabric_count", -1),
            "import_avatar": ("get_avatars", 1),
            "copy_colorway": ("get_colorways", 1),
            "delete_colorway": ("get_colorways", -1),
        }
        t0 = time.time()
        try:
            check = count_checks.get(tool)
            if check:
                before_ok, before = box["srv"].call(check[0])
                if not before_ok:
                    raise ValueError("Cannot read precondition: " + str(before))
            if tool == "import_avatar":
                patterns_ok, patterns_before = box["srv"].call("get_pattern_list")
                if not patterns_ok:
                    raise ValueError("Cannot read garment before avatar import")
            ok, payload = box["srv"].call(tool, args, timeout)
            if ok and tool == "import_avatar":
                patterns_ok, patterns_after = box["srv"].call("get_pattern_list")
                if not patterns_ok or patterns_before != patterns_after:
                    raise ValueError("Avatar import changed the garment patterns")
            if ok and check:
                after_ok, after = box["srv"].call(check[0])
                delta = after.get("count", 0) - before["count"] if after_ok else 0
                # CLO may also duplicate linked/symmetric pieces.
                if not after_ok or (delta * check[1]) < 1:
                    raise ValueError(f"{tool}: expected count change {check[1]}, got {delta}")
            if ok and tool == "set_pattern_name":
                _, actual = box["srv"].call("get_pattern_info", {"pattern_index": args["pattern_index"]})
                if actual.get("name") != args["name"]:
                    raise ValueError("Pattern rename did not persist")
            if ok and tool == "new_project":
                _, actual = box["srv"].call("get_pattern_count")
                if actual.get("count") != 0:
                    raise ValueError("New project still contains patterns")
        except (ValueError, KeyError, TypeError) as exc:
            ok, payload = False, "Postcondition failed: " + str(exc)
        except (queue.Empty, IndeterminateCommand) as exc:
            ACTIVE["uncertain"] = True
            raise IndeterminateCommand(f"{tool} did not finish with a known outcome: {exc}") from exc
        dt = time.time() - t0
        results.append((tool, ok, dt, payload, note))
        (scratch / "results.json").write_text(json.dumps(results, indent=2))
        flag = "ok  " if ok else "FAIL"
        summary = "" if ok else f"  <- {str(payload)[:100]}"
        print(f"  {flag} {tool:<26} {dt:6.2f}s {note}{summary}")
        return ok, payload

    # ── 0. connectivity ───────────────────────────────────────────────────
    print("[0] connectivity")
    wait_s = 0
    for a in sys.argv[1:]:
        if a.startswith("--wait="):
            wait_s = int(a.split("=", 1)[1])
    deadline = time.time() + wait_s
    ok = False
    first = True
    while True:
        try:
            ok, payload = srv.call("ping", {}, 10)
        except queue.Empty:
            ok, payload = False, "no response"
        if ok or time.time() >= deadline:
            break
        if first:
            print(f"  waiting up to {wait_s}s for the bridge — in CLO3D run:")
            print("    Plugins > Plug-in > MCP Bridge (serve)")
            first = False
        srv.close()
        time.sleep(3)
        srv = Server()
        ACTIVE["server"] = srv
    results.append(("ping", ok, 0.0, "" if ok else payload, ""))
    print(f"  {'ok  ' if ok else 'FAIL'} ping")
    if not ok:
        print("\nThe bridge is not responding. In CLO3D:")
        print("  Plugins > Plug-in > MCP Bridge (serve)")
        print("Use the blocking menu launcher; see README.md.")
        return 1

    ACTIVE["connected"] = True
    box["srv"] = srv
    all_tools = {t["name"] for t in srv._rpc("tools/list", {})["result"]["tools"]}
    backup = scratch / "original-scene.zprj"
    ok, payload = run("backup", "save_project", {"file_path": str(backup)})
    if not ok:
        print("Cannot verify a scene backup; aborting before opening the test garment")
        return 1
    ACTIVE["backup"] = str(backup)

    # ── 1. open the garment copy ──────────────────────────────────────────
    print("\n[1] project")
    if not run("open", "open_file", {"file_path": str(garment)})[0]:
        print("Opening the garment copy failed; aborting mutations")
        return 1
    run("info", "get_project_info")
    run("garment", "get_garment_info")
    run("refresh", "refresh_view")
    run("preview", "set_live_preview", {"enabled": False})

    # ── 2. read-only introspection ────────────────────────────────────────
    print("\n[2] read-only introspection")
    ok, pc = run("count", "get_pattern_count")
    n_pat = pc.get("count", 0) if ok and isinstance(pc, dict) else 0
    state["patterns_before"] = n_pat
    run("list", "get_pattern_list")
    if n_pat:
        run("info", "get_pattern_info", {"pattern_index": 0})
        run("bbox", "get_pattern_bounding_box", {"pattern_index": 0})
        run("fabric-of", "get_fabric_for_pattern", {"pattern_index": 0})
    run("arrange", "get_arrangement_list")
    ok, fc = run("fab-count", "get_fabric_count")
    state["fabrics_before"] = fc.get("count", 0) if ok and isinstance(fc, dict) else 0
    run("fab-list", "get_fabric_list")
    ok, cw = run("colorways", "get_colorways")
    state["colorways_before"] = cw.get("count", 0) if ok and isinstance(cw, dict) else 0
    run("avatars", "get_avatars")
    run("genders", "get_avatar_genders")

    # ── 3. non-destructive mutation ───────────────────────────────────────
    print("\n[3] non-destructive mutation")
    if n_pat:
        run("rename", "set_pattern_name", {"pattern_index": 0, "name": "MCP Test Piece"})
        run("flip", "flip_pattern", {"pattern_index": 0, "horizontal": True, "each": True})
    if state["fabrics_before"]:
        run("colour", "set_fabric_color",
            {"fabric_index": 0, "r": 220, "g": 40, "b": 90, "a": 255, "material_face": 0})
        if n_pat:
            run("assign", "assign_fabric_to_pattern",
                {"fabric_index": 0, "pattern_index": 0, "assign_option": 1})
    if state["colorways_before"]:
        run("cw-switch", "set_current_colorway", {"colorway_index": 0})
        run("cw-rename", "set_colorway_name", {"colorway_index": 0, "name": "MCP Test CW"})
    run("avatar-vis", "show_hide_avatar", {"show": True})
    run("sim-quality", "set_simulation_quality", {"quality": 0, "simulation_mode": 0})
    run("simulate", "simulate", {"steps": 10}, timeout=300, note="(10 steps)")

    # ── 4. additive — records indices for the destructive phase ───────────
    print("\n[4] additive")
    ok, _ = run("create", "create_pattern",
                {"points": [[0, -300, 0], [0, -200, 0], [100, -200, 0], [100, -300, 0]]})
    if ok:
        ok2, pc2 = run("recount", "get_pattern_count")
        if ok2 and isinstance(pc2, dict) and pc2.get("count", 0) > n_pat:
            state["new_pattern"] = pc2["count"] - 1
    if n_pat:
        run("copy-pat", "copy_pattern", {"pattern_index": 0, "x": 50, "y": 50})

    zfab = first_asset("Fabric", ".zfab")
    if zfab:
        ok, r = run("import-fab", "import_fabric", {"file_path": zfab})
        if ok and isinstance(r, dict) and isinstance(r.get("fabric_index"), int):
            state["new_fabric"] = r["fabric_index"]
        run("add-fab", "add_fabric", {"file_path": zfab})
        if state.get("new_fabric") is not None:
            run("replace-fab", "replace_fabric",
                {"fabric_index": state["new_fabric"], "file_path": zfab})
    else:
        print("  skip fabric import/add/replace (no .zfab asset found)")

    if state["colorways_before"]:
        ok, r = run("copy-cw", "copy_colorway", {"colorway_index": 0, "copy_option": 0})
        if ok and isinstance(r, dict) and isinstance(r.get("new_index"), int):
            state["new_colorway"] = r["new_index"]

    avt = first_asset("Avatar", ".avt")
    if avt:
        run("import-avatar", "import_avatar", {"file_path": avt, "apf_path": ""}, timeout=300)
    else:
        print("  skip import_avatar (no .avt asset found)")

    # ── 5. exports ────────────────────────────────────────────────────────
    print("\n[5] exports")
    # ExportOBJ opens a modal options dialog: the bridge's poll loop is blocked
    # until it is confirmed, so allow far longer than a normal call and run
    # tools/dialog_watcher.py alongside for an unattended run.
    run("obj", "export_obj", {"file_path": str(out / "g.obj")},
        timeout=600, note="(modal dialog - needs confirm)")
    run("obj+opt", "export_obj",
        {"file_path": str(out / "g2.obj"), "options": {"bExportAvatar": False}},
        timeout=600, note="(native options)")
    run("fbx", "export_fbx", {"file_path": str(out / "g.fbx")})
    run("glb", "export_glb", {"file_path": str(out / "g.glb")})
    run("gltf", "export_gltf", {"file_path": str(out / "g.gltf")})
    run("thumb", "export_thumbnail", {"file_path": str(out / "thumb.png")})
    run("snapshot", "export_snapshot", {"file_path": str(out / "snap.png")})
    run("turntable", "export_turntable",
        {"file_path": str(out / "turn.png"), "number_of_images": 4,
         "width": 512, "height": 512}, timeout=300, note="(4 frames @512)")
    run("techpack", "export_tech_pack", {"file_path": str(out / "techpack.json")})

    # ── 6. destructive — only objects this run created ────────────────────
    print("\n[6] destructive (only on objects created above)")
    if state.get("new_pattern") is not None:
        run("del-pattern", "delete_pattern", {"pattern_index": state["new_pattern"]})
    else:
        print("  skip delete_pattern (no pattern was created)")
    if state.get("new_fabric") is not None:
        run("del-fabric", "delete_fabric", {"fabric_index": state["new_fabric"]})
    else:
        print("  skip delete_fabric (no fabric was imported)")
    if state.get("new_colorway") is not None:
        run("del-colorway", "delete_colorway", {"colorway_index": state["new_colorway"]})
    else:
        print("  skip delete_colorway (no colorway was copied)")

    # ── 7. save, then new_project last (it discards the document) ─────────
    print("\n[7] save + reset")
    run("save", "save_project", {"file_path": str(out / "saved.zprj")})
    run("new", "new_project", note="(test copy only)")
    run("import-file", "import_file", {"file_path": str(garment)})

    restored, _ = run("restore", "open_file", {"file_path": ACTIVE["backup"]})
    if restored:
        ACTIVE.pop("backup")
        ACTIVE["stopped"] = run("stop", "stop_bridge")[0]
    called = {r[0] for r in results}
    passed = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    (scratch / "results.json").write_text(json.dumps(results, indent=2))
    print("\n" + "=" * 72)
    print(f"tools exercised : {len(called)}/{len(all_tools)}")
    print(f"calls passed    : {len(passed)}")
    print(f"calls failed    : {len(failed)}")
    skipped = sorted(all_tools - called)
    if skipped:
        print(f"never called    : {', '.join(skipped)}")
    if failed:
        print("\nfailures:")
        for tool, _, _, err, _ in failed:
            print(f"  {tool:<26} {str(err)[:150]}")
    produced = sorted(p.name for p in out.rglob("*") if p.is_file())
    print(f"\nfiles produced ({len(produced)}): {', '.join(produced[:20]) or 'none'}")
    print(f"scratch dir     : {scratch}")
    return 1 if failed or skipped else 0


def main():
    if "--run-live" not in sys.argv:
        print("Prepared only: no MCP calls or CLO actions were performed.")
        print("See docs/live-test-checklist.md. When CLO is available, run:")
        print("  uv run python tools/live_test.py /absolute/garment.zprj --run-live")
        return 0
    ACTIVE.clear()
    status = 1
    try:
        status = exercise()
    except (queue.Empty, IndeterminateCommand) as exc:
        ACTIVE["uncertain"] = True
        print("Live run stopped:", exc)
    finally:
        srv = ACTIVE.get("server")
        if srv:
            try:
                if ACTIVE.get("uncertain"):
                    print("Outcome unknown; inspect CLO, then restore manually from:", ACTIVE.get("backup"))
                    status = 1
                elif ACTIVE.get("backup"):
                    ok, payload = srv.call("open_file", {"file_path": ACTIVE["backup"]})
                    print("Scene restoration:", "ok" if ok else payload, flush=True)
                    if not ok:
                        status = 1
                        print("Restore manually from:", ACTIVE["backup"])
                if ACTIVE.get("connected") and not ACTIVE.get("stopped") and not ACTIVE.get("uncertain"):
                    srv.call("stop_bridge", timeout=10)
            except Exception as exc:
                status = 1
                print("Cleanup could not finish:", exc, "backup:", ACTIVE.get("backup"))
            finally:
                if ACTIVE.get("connected") and not ACTIVE.get("stopped"):
                    _release_bridge()
                srv.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
