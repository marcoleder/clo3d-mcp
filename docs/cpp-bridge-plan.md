# C++ bridge — high-level plan

Draft, 2026-09-22. Replaces the in-CLO **Python** bridge with a **C++ CLO plug-in**.
The MCP server, its 45 tools and the wire protocol stay exactly as they are.

Everything below was measured against CLO **2026.1.224** on macOS / Apple Silicon.
Nothing here is speculative; where something is unverified it says so.

---

## STATUS UPDATE — 2026-09-22, after building the hybrid

**Four of the six reasons for a full C++ port have been solved without one.**

The cheap path won. A ~200-line C++ shim loaded via `ctypes`, plus one snapshot
trick, covered almost everything:

| Original reason for C++ | Status now |
|---|---|
| 4 exports uncallable (`fbx`, `glb`, `gltf`, `tech_pack`) | **SOLVED** — `cpp/clo_shim.cpp`, verified against a real garment |
| Export options never work | **SOLVED** — `bExportAvatar=False` gave 51,869 verts vs 57,784; the flag really reached CLO |
| Modal dialogs block the bridge | **SOLVED for exports** — the shim calls the non-dialog overloads |
| No live preview | **SOLVED** — `ExportSnapshot3D` forces a real repaint; 8 consecutive colour changes all visible |
| **CLO frozen — not interactive while driven** | **STILL OPEN — only C++ fixes this** |
| Free repaints (vs ~0.3s + 800 KB PNG each) | **STILL OPEN — only C++ fixes this** |

### Revised recommendation

**Do not port 45 handlers.** The remaining benefit is narrow: being able to pan,
rotate and click in CLO *while* a batch runs, and repaints that cost nothing.

Build the C++ QTimer bridge only if interactivity is worth it on its own. If
watching a batch update is enough, the current hybrid already delivers that.

If it is built, Phase 0 (`QTimer` survives a menu action) remains the whole
risk, and the shim's export code ports across directly — nothing done so far is
wasted.

---

## Where we are today

Live-tested against a real 14-pattern / 16 MB garment.

**All 47 tools work.** The C++ shim closed the last gaps:

| | |
|---|---|
| Python handlers | 42 tools — scene, patterns, fabrics, colorways, avatars, simulation, `export_obj`, thumbnails, snapshots, turntable |
| Via `cpp/clo_shim.cpp` | `export_fbx`, `export_glb`, `export_gltf`, `export_tech_pack`, and options on every export |
| Added along the way | `refresh_view`, `set_live_preview` |

Proof these are real files, not just "no exception raised":

- `export_obj` → **57,784 verts / 108,176 faces / 19 materials**, + MTL + 13 textures
- `export_fbx` → 3.4 MB, header `Kaydara FBX Binary`
- `export_glb` → 3.7 MB, magic `glTF`
- `export_gltf` → 41 KB JSON + 2.86 MB `.bin`, 16 meshes
- options honoured: `bExportAvatar=False` → 51,869 verts (vs 57,784)

How it runs, and the one thing still unsatisfying:

- Launched from **Plugins ▸ Plug-in ▸ "MCP Bridge (serve…)"**, registered in
  `~/Documents/CLO/Plugins/pluginSettings.json` (read at startup and on *Refresh Plug-in*).
- It **blocks CLO's main thread** for up to 900 s, with a `stop` sentinel so the client
  releases CLO the moment a batch ends.
- `set_live_preview` makes the viewport update as the batch runs, so the freeze is
  visible-but-watchable rather than opaque.
- `tools/dialog_watcher.py` handles the remaining modal dialogs (`Open Project` when a
  project is already loaded, OBJ import/export options).

**The freeze is the only remaining reason to consider C++.** You can watch, but you
cannot interact.

---

## Why C++

Four problems, each with the evidence that established it.

### 1. Four exports are uncallable, and options never work

`ExportFBX`, `ExportGLB`, `ExportGLTF`, `ExportTechPack` each require
`Marvelous::ImportExportOption` or `ExportTechpackOption`. **CLO registers no Python
classes at all** — `dir()` yields zero types across `export_api`, `fabric_api`,
`import_api`, `pattern_api`, `utility_api`.

pybind11 confirms it by reporting the parameter under its raw C++ name, which is how it
renders an *unregistered* type (a registered one would print `export_api.ImportExportOption`):

```
ExportGLB(): incompatible function arguments. The following argument types are supported:
    1. (arg0: str, arg1: Marvelous::ImportExportOption) -> List[str]
```

No Python expression can produce such a value, and **none of the four has an option-free
overload**. `export_obj` escapes only because `ExportOBJ(filePath)` exists — which is also
why passing *options* to `export_obj` fails while the plain call succeeds.

**C++ constructs these structs directly.** This unlocks 4 tools and makes export options
work everywhere.

### 2. Modal dialogs block the bridge

`ExportOBJ` and the `Export*WithDialog` variants open a **modal options dialog** ("Save
Colorways", "Unified UV Coordinates", "Save with Meta Data"). While it is up, CLO is not
running the bridge's poll loop, so an unattended batch stalls.

This is what a mysterious 182 s / 240 s "timeout" on an export actually means: the call is
not slow, it is waiting for a human. Today `tools/dialog_watcher.py` clicks OK via
AppleScript.

**C++ calls the non-dialog overloads** — `ExportGLB(path, options)` rather than
`ExportGLBWithDialog(path)`. The watcher becomes unnecessary.

### 3. The bridge has to freeze CLO to run at all

Two modes were tested, and only one works:

| Mode | Result |
|---|---|
| Background daemon thread | **Starves.** CLO never re-enters Python after a plug-in script returns, so the GIL is never yielded and the thread silently stops serving. It reports `alive=True` while doing nothing. |
| Blocking the main thread | **Works**, ~197 calls in 60 s with zero errors — but CLO is unresponsive throughout. |

There is no Python escape hatch: CLO ships **no PySide/shiboken** (so no `QTimer` from
Python), its Python API exposes **no timer or idle hook**, `RestAPIInterface` is
**outbound-only** (`CallRESTGet`/`CallRESTPost` call *other* services — CLO does not serve
HTTP), and `CloEventPlugin` only offers mouse-drop events on the 2D/3D views.

**A `QTimer` on CLO's existing Qt event loop fires on the main thread without blocking it.**
You could work in CLO while Claude drives it — and this is now the *only* thing
C++ still uniquely buys.

Note what this is **not** an argument for any more: *seeing* a batch happen live
is already solved. `export_api.ExportSnapshot3D()` forces a genuine repaint even
while the main thread is blocked (`Refresh3DWindow()` and `ExportThumbnail3D()`
do not — the first posts an event nothing handles, the second renders offscreen).
The `set_live_preview` tool uses it after every state-changing command. What
remains missing is *interactivity*: you can watch, but you cannot click.

### 4. A whole class of crash disappears

A starved Python thread is **not dead, only unscheduled**. The moment any later inline loop
calls `time.sleep()` and yields the GIL, that zombie wakes up inside module state CLO may
have torn down, with two poll loops racing the same files. This crashed CLO during testing.
No threads, no GIL, no zombie class.

---

## What C++ does *not* buy

**Not more API surface.** This was assumed and then measured — it is false:

| module | C++ functions | Python attributes |
|---|---|---|
| export_api | 88 | 89 |
| fabric_api | 134 | 135 |
| import_api | 38 | 39 |
| pattern_api | 203 | 203 |
| utility_api | 359 | 359 |
| **total** | **822** | **825** |

Effectively identical. Anyone arguing "C++ exposes more of CLO" is wrong, and the plan
should not be sold on it. *(Methodological note: this was believed true until measured.
Measure the claim before it reaches a decision document.)*

**Not stability.** It is a **regression** in one respect: a Python exception returns a clean
error to the caller, whereas a C++ segfault takes CLO down with it. Defensive coding is not
optional.

**Not faster iteration.** See Risks — a C++ plug-in needs a CLO restart to reload, where the
Python bridge only needed a menu click.

---

## Architecture

The wire protocol is the contract and does not change:

```
MCP server  (unchanged — 45 tools, same schemas, same param names)
     |  file IPC:  ~/clo3d_mcp/{request,response}.json
     v
C++ CLO plug-in  (new)
     QTimer(~100ms) on CLO's Qt event loop   <- main thread, non-blocking
       -> read request.json
       -> dispatch on "type"
       -> call PATTERN_API / EXPORT_API / FABRIC_API / UTILITY_API / IMPORT_API
       -> write response.json atomically (temp + rename)
```

Consequences of keeping the protocol:

- `src/clo3d_mcp/` is untouched — **zero MCP or tool-schema work**.
- `tools/live_test.py` works unchanged; it speaks JSON over files, not Python.
- **Both bridges can serve the same test suite**, which makes differential testing possible.

JSON: use `QJsonDocument`. Qt is already linked, so no new dependency.

Retain from the Python bridge, because each earned its place:

- the **`stop` sentinel** (harmless once non-blocking, still useful for clean shutdown)
- **`bridge.log`** — a menu-launched plug-in has no visible stdout; without a log file its
  failures are invisible by construction, which cost real debugging time
- a **`ping`** command — the fastest way to tell a dead bridge from a slow one
- **`debug_*` commands** kept out of the MCP tool list (the verifier exempts the prefix)

---

## Porting strategy

Each Python handler is a thin wrapper — read a params dict, call one or two API functions,
return a dict. The port is mechanical, and three assets already exist:

1. **`plugin/clo3d_mcp_plugin.py`** — the behavioural spec. 45 handlers, each corrected
   against real CLO behaviour.
2. **`api_map2.json`** (regenerate via `tools/verify_against_clo.py`) — 823 functions /
   1073 overloads parsed from the SDK headers, with arities, defaults and return types.
3. **The tool schemas** — exact param names and types the server sends.

Port handler-by-handler, keeping names aligned (`handle_export_obj` → `handleExportObj`) so
the two implementations stay diffable by eye.

### The oracle trick

Keep the Python bridge working. For any request, run it against **both** bridges and diff
the JSON responses. Divergence is a porting bug.

This turns "did I port 45 handlers correctly?" from a judgement call into a test, costs
nothing because both speak the same protocol, and is **the single highest-value idea in
this plan**.

### Bugs already found — do not reintroduce them

The Python bridge's history is a list of traps the C++ port can walk straight back into:

| Bug | Lesson for the port |
|---|---|
| `SetSimulationQuality(quality)` — SDK needs `(quality, simulationMode)` | Check arity against the headers, not against the old code |
| `CopyColorway(index)` — needs `(index, copyOption)`, returns the new index | Don't discard return values |
| `ExportTechPack` returns **void** — `bool(result)` reported failure on every success | Check return *types*, not just arity |
| `replace_fabric` tool had **no handler** at all | Verify wiring in both directions |
| `export_glb`/`gltf` accepted an `options` dict and **silently discarded it** | Worse than a crash — success reported, defaults used |
| `export_thumbnail(width, height)` — parameters that **do not exist** in the API | Don't invent parameters the API can't honour |
| `create_pattern` rejected integer coordinates | pybind11-specific; see below |

That last one is Python-only and **disappears in C++**: `CreatePatternWithPoints` takes
`vector<tuple<float,float,int>>`, and pybind11 calls **nested** type casters with
`convert=False`, so a Python `int` is rejected rather than promoted. C++ has no such
problem.

---

## Phasing

Each phase ends with `tools/live_test.py` green for its subset.

| Phase | Scope | Purpose |
|---|---|---|
| **0** | Plug-in loads, installs a `QTimer`, answers `ping` | **De-risks the whole plan.** Verify the timer survives after the menu action returns, and that CLO stays interactive. Stop here if it doesn't. |
| 1 | ~15 read-only handlers (`get_*`) | Proves dispatch, JSON, param decoding. Cannot damage a document. |
| 2 | ~12 mutation handlers | |
| 3 | ~9 export handlers | **The payoff** — the 4 currently impossible ones, plus options, plus no dialogs. |
| 4 | destructive + project handlers | Last, for the same reason the test suite runs them last. |
| 5 | Decide the Python bridge's fate | Keep as oracle/fallback, or retire. |

**Phase 0 carries the entire unknown risk; everything after it is repetitive.** Build it
first and in isolation. If the timer doesn't survive, the plan is dead and it cost an
afternoon rather than a week.

---

## Risks

- **`QTimer` persistence is unverified.** The plug-in's `DoFunction()` is called on a menu
  click; the timer must keep firing after that call returns.
  `LibraryWindowImplementation` proves plug-ins run inside CLO's `QApplication` (it calls
  `QApplication::topLevelWidgets()`), but not that a timer survives. Phase 0 settles it.
- **Crashes take CLO with them.** Validate every param, bounds-check every index, wrap
  handlers in `try/catch`, never trust the request file.
- **Build discipline** (all established and working — see `CLAUDE.md`):
  - **Release only.** Debug dylibs do not load in CLO.
  - **arm64, never Rosetta.**
  - **Always run `retarget-qt.sh`** after building, or the plug-in links Homebrew Qt by
    absolute path and drags a *second* Qt into CLO's process alongside its own 6.10.3 —
    duplicate metatype registries, and it crashes.
  - Samples have no top-level `CMakeLists.txt`; configure each directory directly.
- **Reload cost.** A C++ plug-in needs a CLO restart; the Python bridge needed a menu
  click. Batch changes accordingly.
- **The toolchain itself is proven** — `ExportPlugin` and `LibraryWindowImplementation`
  both build, retarget cleanly and install. This is not new ground.

---

## Testing

Everything already built carries over:

| Asset | Status under C++ |
|---|---|
| `tools/live_test.py` | **Unchanged.** Protocol-level: copies the garment, exports to a scratch dir, deletes only what it created, runs `new_project` last, releases the bridge via `atexit`. |
| `tools/dialog_watcher.py` | Should become **unnecessary** — its disappearance is a success signal. |
| `tools/verify_against_clo.py` | **Needs a C++ variant.** Header parsing and the handler↔tool wiring check carry over; the call-site arity/return checks read Python AST today. |
| Differential oracle | **New**, and the most valuable addition. |

The dispatch layer should also be testable outside CLO against a stubbed API, so most
porting bugs surface without a CLO restart.

---

## Where docs live

- **`/Users/port/Qt-6.11.2/CLAUDE.md`** — operational notes for this machine: the Qt
  build/run split and `retarget-qt.sh`, the arm64 rule, plug-in paths, how to discover
  CLO's real API surface, and the bridge findings. **This is what the next session reads**
  — add a C++ bridge section here.
- **`docs/` in this repo** (this file) — design and rationale.
- **`~/clo3d_mcp/bridge.log`** — runtime evidence.

### Keep the "why" findings — they are expensive to rediscover

- pybind11 calls **nested** type casters with `convert=False`; ints are not promoted to floats.
- CLO registers **no Python classes**, so no API taking a struct parameter is callable.
- **`strings` on a dylib proves nothing** about what pybind11 bound. `ImportExportOption`
  appears in `libCloScene.dylib` and is still unreachable from Python. Confirm with `dir()`
  on the live module.
- **Modal dialogs block the bridge**; an export "timeout" usually means a dialog is open.
  Inspect with:
  `osascript -e 'tell application "System Events" to tell process "CLO" to get name of every window'`
- **Starved Python threads are not dead** and will crash CLO when something later yields
  the GIL.
- CLO's Python API function names **contain digits** (`ExportSnapshot3D`,
  `ExportThumbnail3D`). A `[A-Za-z_]+` regex silently truncates them and invents "missing
  API" results.

---

## Open questions

1. **Does a `QTimer` installed from a plug-in menu action survive and keep firing?**
   *(Phase 0 — answer before committing to anything else.)*
2. Should the C++ plug-in auto-start at CLO launch, or stay menu-triggered? Auto-start is
   friendlier but harder to disable when something goes wrong.
3. Retire the Python bridge, or keep it as the oracle and a fallback?
4. **Is `export_tech_pack` worth porting at all?** `ExportTechPackToStream(path)` takes no
   option type and may already be reachable from Python. Five minutes of checking could
   remove a handler from the port.
5. Do `export_glb` / `export_gltf` actually work via their dialog variants? Still
   unverified — they were gated out of the last run to stop a modal dialog stalling the
   batch. Worth confirming, since it sets the true Python baseline the C++ port is measured
   against.
