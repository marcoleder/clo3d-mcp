#!/usr/bin/env python3
"""Verify this MCP server against the installed CLO SDK + CLO.app.

Static checks, no CLO run needed. Re-run after any CLO or SDK update:

    python3 tools/verify_against_clo.py

Checks
  1. wiring   — every bridge handler has a tool, and vice versa
  2. existence— every *_api.X call exists in CLO.app's Python bindings
  3. arity    — every call matches an SDK overload (honouring C++ default args);
                calls inside try/except or if/else fallbacks are allowed to differ
  4. returns  — no void-returning API has its result used as a success flag

Exit code 0 = clean.
"""
import ast
import collections
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SDK = pathlib.Path("/Users/port/Qt-6.11.2/CLO_SDK_v2026.1.224_Mac/CLOAPIInterface/include")
BINDINGS = pathlib.Path("/Applications/CLO.app/Contents/Frameworks/libCloScene.dylib")

MODULES = {"pattern_api", "utility_api", "export_api", "fabric_api", "import_api", "rest_api"}
# structs exposed to Python as constructible types, not virtual methods
STRUCTS = {"ImportExportOption", "NewImportExportOption", "ExportTechpackOption"}

PLUGIN = REPO / "plugin" / "clo3d_mcp_plugin.py"
SERVER = REPO / "src" / "clo3d_mcp" / "server.py"

failures = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL  {msg}")


# ── parse the SDK headers into {name: [overload, ...]} ─────────────────────
# NOTE: the tail must accept ';', '{' *or* end-of-line — some declarations wrap
# their brace to the next line (e.g. ExportTurntableImages).
SIG = re.compile(
    r"^\s*virtual\s+(.+?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)"
    r"\s*(?:const\s*)?(?:=\s*0\s*)?(?:[;{]|\s*$)"
)


def split_args(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def load_sdk():
    api = collections.defaultdict(list)
    for h in sorted(SDK.glob("*APIInterface.h")):
        text = re.sub(r"\(\s*\n\s*", "(", h.read_text(errors="replace"))
        for line in text.splitlines():
            m = SIG.match(line.split("//")[0])
            if not m:
                continue
            ret, name, argstr = m.groups()
            if name.startswith("~"):
                continue
            args = split_args(argstr)
            ndef = sum(1 for a in args if "=" in a)
            api[name].append({"ret": ret.strip(), "min": len(args) - ndef, "max": len(args)})
    return api


def load_bindings():
    if not BINDINGS.exists():
        print(f"  skip  {BINDINGS} not found — existence check skipped")
        return None
    out = subprocess.run(["strings", "-a", str(BINDINGS)], capture_output=True, text=True).stdout
    return {s for s in out.splitlines() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,60}", s)}


def main():
    api = load_sdk()
    print(f"SDK: {len(api)} functions, {sum(len(v) for v in api.values())} overloads")
    symbols = load_bindings()

    plugin_src = PLUGIN.read_text()
    server_src = SERVER.read_text()
    tree = ast.parse(plugin_src)

    # 1. wiring
    print("\n[1] handler <-> tool wiring")
    handlers = set(re.findall(r'"([a-z0-9_]+)"\s*:\s*handle_', plugin_src))
    sends = set(re.findall(r'_send\(\s*"([a-z0-9_]+)"', server_src))
    for c in sorted(handlers - sends):
        if c.startswith("debug_"):
            continue  # diagnostic commands are deliberately not MCP tools
        fail(f"bridge handles '{c}' but no tool exposes it")
    for c in sorted(sends - handlers):
        fail(f"tool sends '{c}' but the bridge has no handler")
    if handlers == sends:
        print(f"  ok    {len(handlers)} handlers <-> {len(sends)} tools")

    # nodes inside except handlers / else branches are permitted fallbacks
    guarded = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                guarded.update(id(x) for x in ast.walk(h))
        if isinstance(n, ast.If):
            for b in n.orelse:
                guarded.update(id(x) for x in ast.walk(b))

    captured = {
        id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
    }

    # 1b. parameter wiring: what a tool sends vs what its handler reads
    print("\n[1b] parameter wiring")
    server_tree = ast.parse(server_src)

    def payload_keys(fn_node, arg):
        """Keys in a _send payload — inline dict, or a dict built in a local var."""
        if isinstance(arg, ast.Dict):
            return {k.value for k in arg.keys if isinstance(k, ast.Constant)}
        if isinstance(arg, ast.Name):
            keys = set()
            for st in ast.walk(fn_node):
                # params = {...}   and   params: dict = {...}   (AnnAssign)
                targets = []
                if isinstance(st, ast.Assign):
                    targets = st.targets
                elif isinstance(st, ast.AnnAssign) and st.target is not None:
                    targets = [st.target]
                if targets and isinstance(getattr(st, "value", None), ast.Dict):
                    if any(getattr(t, "id", None) == arg.id for t in targets):
                        keys |= {k.value for k in st.value.keys if isinstance(k, ast.Constant)}
                # params["k"] = ...
                for t in targets:
                    if (isinstance(t, ast.Subscript) and getattr(t.value, "id", None) == arg.id
                            and isinstance(t.slice, ast.Constant)):
                        keys.add(t.slice.value)
            return keys
        return set()

    sends_keys = {}
    for fn_node in [n for n in ast.walk(server_tree) if isinstance(n, ast.FunctionDef)]:
        for n in ast.walk(fn_node):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_send":
                cmd = n.args[0].value
                sends_keys[cmd] = payload_keys(fn_node, n.args[1]) if len(n.args) > 1 else set()

    reads_keys = {}
    for fn_node in [n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name.startswith("handle_")]:
        keys = set()
        for n in ast.walk(fn_node):
            if isinstance(n, ast.Subscript) and getattr(n.value, "id", "") == "params" \
               and isinstance(n.slice, ast.Constant):
                keys.add(n.slice.value)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "get" \
               and getattr(n.func.value, "id", "") == "params" and n.args \
               and isinstance(n.args[0], ast.Constant):
                keys.add(n.args[0].value)
        reads_keys[fn_node.name[len("handle_"):]] = keys

    nparam = 0
    for cmd in sorted(sends_keys):
        s_, r_ = sends_keys[cmd], reads_keys.get(cmd, set())
        for k in sorted(s_ - r_):
            fail(f"tool '{cmd}' sends '{k}' but the handler never reads it")
        for k in sorted(r_ - s_):
            fail(f"handler '{cmd}' reads '{k}' but no tool can send it")
        if not (s_ - r_) and not (r_ - s_):
            nparam += 1
    print(f"  ok    {nparam}/{len(sends_keys)} commands with matching parameters")

    print("\n[2/3] API existence + arity")
    n_ok = 0
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        v = n.func.value
        if not (isinstance(v, ast.Name) and v.id in MODULES):
            continue
        fn, where = n.func.attr, f"{PLUGIN.name}:{n.lineno}"

        if symbols is not None and fn not in symbols and fn not in STRUCTS:
            fail(f"{where} {v.id}.{fn} is not present in CLO.app's bindings")
            continue

        overloads = api.get(fn)
        if overloads is None:
            if fn not in STRUCTS:
                fail(f"{where} {v.id}.{fn} not found in SDK headers")
            continue

        arities = sorted({k for o in overloads for k in range(o["min"], o["max"] + 1)})
        if len(n.args) not in arities:
            if id(n) not in guarded:
                fail(f"{where} {v.id}.{fn} called with {len(n.args)} arg(s); SDK accepts {arities}")
            continue

        # 4. void return used as a success flag
        if {o["ret"] for o in overloads} == {"void"} and id(n) in captured:
            fail(f"{where} {v.id}.{fn} returns void but its result is captured/used")
            continue
        n_ok += 1
    print(f"  ok    {n_ok} call sites verified")

    print()
    if failures:
        print(f"{len(failures)} problem(s)")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
