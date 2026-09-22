# CLO3D MCP Server

Talk to CLO3D from Codex, Claude, Cursor, or any MCP client. Create patterns, swap fabrics, run simulations, export models. All from a chat window.

```
Your AI assistant  <-->  MCP Server  <-->  CLO3D Plugin  <-->  CLO3D
```

> **This is a fork** of [Ubani-Studio/clo3d-mcp](https://github.com/Ubani-Studio/clo3d-mcp),
> fixed and extended for **CLO 2026.1** on **macOS / Apple Silicon**.
> The bug fixes are offered upstream in [PR #2](https://github.com/Ubani-Studio/clo3d-mcp/pull/2);
> the rest lives here. See [what this fork changes](#what-this-fork-changes).

**Verification status (2026-09-22):** all **48 tools** passed the live suite on
CLO 2026.1.224 / macOS arm64: **52 calls, zero failures**, including avatar import
and turntable images. The offline suite has **95 passing tests**. The
[review follow-up](docs/review-followup-2026-09-22.md) adds cancelled-open gates,
partial-import retry protection and records a second passing live run. See the
[live validation report](docs/live-validation-2026-09-22.md) for artifacts,
concurrent-client checks and limits, and the [original audit](docs/correctness-audit-2026-09-22.md)
for the problems that prompted these fixes. Windows remains untested.

---

## Requirements

| | |
|---|---|
| CLO3D | **2026.1** (tested against 2026.1.224) |
| Python | 3.10+ for the MCP server (CLO ships its own 3.11 for the plug-in) |
| OS | macOS (Apple Silicon) tested end to end. Windows is **untested** — see [Platform support](#platform-support) |
| Optional | CMake + a C++ compiler, only if you want the [native shim](#optional-native-shim) |

---

## 1. Install the server

The package is **not on PyPI**, so `uvx clo3d-mcp` will not work. Install from source:

```bash
git clone https://github.com/marcoleder/clo3d-mcp
cd clo3d-mcp
uv venv .venv --python 3.12
uv pip install --python .venv -e .
```

That gives you `.venv/bin/clo3d-mcp` (`\.venv\Scripts\clo3d-mcp.exe` on Windows).

> `uvx --from <local path>` caches stale wheels and silently ignores your edits.
> Use the venv entry point.

## 2. Register the bridge inside CLO3D

The plug-in has to run *inside* CLO. Registering it as a menu item is the least
fiddly route — one click, no file dialogs.

Create `pluginSettings.json` in CLO's plug-in folder:

- **macOS** — `~/Documents/CLO/Plugins/pluginSettings.json`
- **Windows** — `C:/Users/Public/Documents/CLO/Plugins/pluginSettings.json`

```json
{
 "plugins": [
  {
   "m_AddingPositionIndex": 0,
   "m_BaseMenuTreeByObjectName": "Plugins / Plug-in",
   "m_PlugInFileName": "/ABSOLUTE/PATH/TO/clo3d-mcp/plugin/start_bridge_blocking.py",
   "m_PlugInIconFileName": "",
   "m_PlugInTitle": "MCP Bridge (serve)",
   "m_SourcePath": "/ABSOLUTE/PATH/TO/clo3d-mcp/plugin/start_bridge_blocking.py",
   "m_SourceType": "script"
  }
 ],
 "version": 2
}
```

Then in CLO: **Plugins ▸ Refresh Plug-in**. The item appears under
**Plugins ▸ Plug-in**.

> CLO reads `pluginSettings.json` at startup and on *Refresh Plug-in* only. If
> your menu item doesn't appear, you skipped the refresh.

<details>
<summary>Script Editor instead (Windows unverified; <b>not</b> on macOS)</summary>

**Script ▸ Script Editor ▸** open `plugin/clo3d_mcp_plugin.py` **▸ Run**.

This starts the bridge on a background thread. On macOS that thread **starves**:
CLO never re-enters Python after a plug-in script returns, so it never gets the
GIL. It reports `alive=True` while serving nothing. Use the menu item above.
</details>

## 3. Connect your MCP client

**Codex (CLI, desktop app, or IDE extension):**

After installing the server above, register its absolute executable path. On
macOS, explicitly match the bridge's default `~/clo3d_mcp` directory:

```bash
codex mcp add clo3d --env CLO3D_MCP_DIR="$HOME/clo3d_mcp" -- /ABSOLUTE/PATH/TO/clo3d-mcp/.venv/bin/clo3d-mcp
codex mcp get clo3d
```

In `~/.codex/config.toml`, add `tool_timeout_sec = 600` under the generated
`[mcp_servers.clo3d]` table. The complete macOS entry looks like this (replace
both absolute paths):

```toml
[mcp_servers.clo3d]
command = "/ABSOLUTE/PATH/TO/clo3d-mcp/.venv/bin/clo3d-mcp"
tool_timeout_sec = 600

[mcp_servers.clo3d.env]
CLO3D_MCP_DIR = "/Users/YOUR_USER/clo3d_mcp"
```

Codex defaults to a 60-second tool timeout; this server can wait 180 seconds
per command (5 seconds for ping) and never retries a command automatically. Restart your Codex client
after changing the configuration, then check `/mcp` in the CLI. Start the CLO
bridge as described below before calling its tools. See the
[official Codex MCP documentation](https://developers.openai.com/codex/mcp/).

On Windows, use the absolute `.venv\Scripts\clo3d-mcp.exe` path and match
`CLO3D_MCP_DIR` to the bridge's `%TEMP%\clo3d_mcp` directory.

**Claude Code:**
```bash
claude mcp add clo3d -- /ABSOLUTE/PATH/TO/clo3d-mcp/.venv/bin/clo3d-mcp
```

**Claude Desktop** — add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "clo3d": {
      "command": "/ABSOLUTE/PATH/TO/clo3d-mcp/.venv/bin/clo3d-mcp"
    }
  }
}
```

The IPC directory must match on both sides. Both now default to `~/clo3d_mcp`
when `TEMP` is unset (macOS), or `%TEMP%/clo3d_mcp` on Windows. WSL clients
auto-detect a Windows user temp directory; use an explicit path when ambiguous.
For a custom directory, set `CLO3D_MCP_DIR` in both the MCP client's server
environment and CLO's environment; setting it in the client does not configure CLO.

## 4. Run it

1. In CLO: **Plugins ▸ Plug-in ▸ MCP Bridge (serve)**
2. **CLO's UI freezes. That is expected** — see [How it works](#how-it-works)
3. Ask your assistant for something
4. Stop the bridge explicitly when finished, or wait for its 15-minute deadline
   (checked between commands). On macOS with the default bridge directory:

   ```bash
   touch "$HOME/clo3d_mcp/stop"
   ```

The ordinary MCP server does not send this stop signal when a conversation
finishes or the client exits. A stop signal or deadline cannot interrupt a
CLO API call or modal dialog already in progress.

Try:
- *"What patterns are in this project?"*
- *"Set the front bodice fabric to red, then simulate 100 steps"*
- *"Export this as GLB without the avatar"*

**Call `ping` before starting a batch.** It waits at most 5 seconds. Other
commands wait up to 180 seconds. Commands are sent once: a timeout does not
cancel a running CLO operation, and its outcome may be unknown. Inspect the
scene before repeating a mutation. Expired queued requests are not executed.

**Upgrade both sides together.** Protocol 2 uses `ready.json` plus separate
`requests/<id>.json` and `responses/<id>.json` files. Restart the MCP server and
restart the bridge menu action after updating the checkout. The bridge imports
the shared standard-library transport from `src/`, so keep the whole checkout.
Older clients and plugins using shared request.json/response.json are incompatible.
Readiness metadata is not a liveness guarantee; use ping after a CLO crash.

Call **`stop_bridge`** when finished to release CLO between commands. This stops
the shared bridge for every client. Client exit alone does not stop it. The
stop-file command above is also available when the MCP client has exited.

---

## The 48 tools

<details>
<summary>Full list</summary>

**Scene** — `get_project_info` `new_project` `open_file` `save_project` `get_garment_info`

**Patterns** — `get_pattern_count` `get_pattern_list` `get_pattern_info`
`get_pattern_bounding_box` `set_pattern_name` `copy_pattern` `delete_pattern`
`flip_pattern` `create_pattern` `get_arrangement_list`

**Fabrics** — `get_fabric_count` `get_fabric_list` `add_fabric` `import_fabric`
`replace_fabric` `delete_fabric` `assign_fabric_to_pattern` `set_fabric_color`
`get_fabric_for_pattern`

**Colorways** — `get_colorways` `set_current_colorway` `set_colorway_name`
`copy_colorway` `delete_colorway`

**Avatars** — `get_avatars` `get_avatar_genders` `show_hide_avatar` `import_avatar`\*

**Simulation** — `simulate` `set_simulation_quality`

**Export** — `export_obj` `export_fbx`\* `export_glb`\* `export_gltf`\*
`export_thumbnail` `export_snapshot` `export_turntable` `export_tech_pack`\*

**Import** — `import_file`

**Session** — `ping` `refresh_view` `set_live_preview` `stop_bridge`

\* AVT import needs native shim ABI 2. FBX/tech pack and export options need the
[native shim](#optional-native-shim) on the tested CLO build. GLB/glTF have dialog
fallbacks only when no options are supplied.

</details>

---

## Watching it work

CLO's viewport does not repaint by itself while the bridge is serving. Turn on
live preview and it redraws after every change:

> *"Turn on live preview, then cycle the fabric through five colours"*

Costs ~0.3s and a ~1 MB PNG per change, so leave it off for long batches.
`refresh_view` does a single repaint on demand.

---

## Optional: native shim

The observed CLO 2026.1.224 Python bindings cannot construct the option types
needed for FBX, GLB, glTF and tech pack exports. The native shim constructs those
C++ types and provides the calls, including OBJ export with options. ABI 2 also
provides AVT import in add mode, preserving the garment. Unknown options fail
before export.

Without the shim, FBX and tech pack return a clear error in the tested CLO build.
GLB/glTF can use dialog fallbacks only when no options were supplied.

```bash
cd cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCLO_SDK_DIR=/path/to/CLO_SDK
cmake --build build --config Release
```

The plug-in picks it up automatically. It links **no Qt** and needs no install
step. See [`cpp/clo_shim.cpp`](cpp/clo_shim.cpp) for how it reaches CLO's own
API pointers. Rebuild after updating: the new library is named
`libclo_shim_v2.dylib` on macOS (`clo_shim_v2.dll` with MSVC). If you use
`CLO_SHIM_PATH`, update it to that library, then restart the bridge.

---

## How it works

**The plug-in** (`plugin/clo3d_mcp_plugin.py`) runs inside CLO3D, polling a
shared directory for session-scoped JSON commands and calling CLO's Python API.

**The MCP server** (`src/clo3d_mcp/`) writes commands there and reads responses.

```
┌─────────────────┐   file-based IPC   ┌──────────────────┐    CLO3D API     ┌────────┐
│   MCP Server    │ ◄────────────────► │   CLO3D Plugin   │ ◄──────────────► │ CLO3D  │
│   (clo3d-mcp)   │  <temp>/clo3d_mcp  │  (Python script) │                  │        │
└─────────────────┘                    └──────────────────┘                  └────────┘
```

**Why CLO freezes while serving.** The poll loop runs on CLO's main thread,
because a background thread never gets scheduled — CLO doesn't re-enter Python
once a plug-in script returns. The loop has a deadline and honours a `stop`
sentinel between commands. Neither can release CLO while an API call is blocked.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| No protocol-2 bridge ready | Start the updated bridge and check both IPC directory settings. |
| A command times out after 180s | Its outcome may be unknown. Inspect CLO before repeating it. |
| Menu item missing | **Plugins ▸ Refresh Plug-in** — `pluginSettings.json` is only read at startup and on refresh |
| Bridge "started" but nothing responds | You used Script Editor on macOS; the thread starves. Use the menu item. |
| An export hangs for minutes | CLO opened a **modal dialog** and is waiting for a click. `tools/dialog_watcher.py` auto-confirms known ones (macOS) |
| Exports succeed but files are empty | The scene is empty — `new_project` discards the document. Open a garment and check `get_pattern_count` first |
| `export_fbx` / `export_tech_pack` refuse | Build the [native shim](#optional-native-shim) |
| Nothing at all works | `~/clo3d_mcp/bridge.log` records every start, including import failures |

---

## Platform support

| | macOS (arm64) | Windows |
|---|---|---|
| MCP server + 48 tools | 48/48 live tools; 95 offline tests | untested |
| Menu-item bridge | protocol 2 and stop/restart tested | untested |
| Script Editor bridge | ❌ thread starves | unverified |
| Native shim | ABI 2 build/load, exports and AVT tested | MSVC configured; build/load untested |
| `dialog_watcher.py` | ✅ AppleScript | ❌ macOS only |

Windows reports welcome.

---

## What this fork changes

**Bug fixes** (offered upstream in [PR #2](https://github.com/Ubani-Studio/clo3d-mcp/pull/2)):
the package couldn't be imported at all (`mcp` 2.x renamed `FastMCP`); several
CLO calls raised `TypeError`; `ExportTechPack` reported failure on success;
`export_glb`/`gltf` silently discarded caller options; `replace_fabric` had no
handler; the comm directory never matched off Windows; 12 handlers had no tool.

**Added here:** the native shim, live preview, the macOS blocking bridge,
`bridge.log`, and test tooling in `tools/`.

---

## Development

```bash
uv sync
uv run python -m pytest tests/ -v  # no CLO needed

python3 tools/verify_against_clo.py         # static checks: wiring, arity, returns
uv run python tools/live_test.py garment.zprj --run-live     # discovers all tools; checks results and artifacts
python3 tools/dialog_watcher.py 600 &       # auto-confirm CLO dialogs (macOS)
```

`verify_against_clo.py` parses the CLO SDK headers and checks every `*_api.X`
call for SDK signatures, approximate arity (honouring C++ default arguments)
and misused void returns, plus handler↔tool wiring in both directions. Binary
name checks and guarded fallbacks cannot establish runtime correctness. Run it after any CLO or
SDK update.

---

## License

MIT for the code authored here. See [LICENSE](LICENSE).

`sdk/` holds CLO Virtual Fashion's interface headers and sample sources and is
**not** covered by that licence: no rights in it are granted here. See
[NOTICE](NOTICE). You need your own CLO3D licence.

## Verification limits and test behavior

`tools/live_test.py` saves the current scene to a scratch backup before opening
a test copy, restores the backup afterward, and stops the bridge. Saving and
restoring changes the active project path to that backup. All scratch files are
retained. A process crash or blocked native call can prevent restoration; the
printed backup path can be opened manually. Confirm CLO's modal dialogs during
the run; `tools/dialog_watcher.py` can handle recognized dialogs on macOS.
The harness exits nonzero for failures **or missing tool coverage**, checks API
failure flags, state changes, model headers/geometry and referenced resources,
and writes `results.json` in its scratch directory. These checks do not establish
visual fidelity or every property of every tool.

`tools/verify_against_clo.py` checks wiring and SDK signatures using the bundled
headers by default (`CLO_SDK_DIR` overrides the SDK root). Binary strings are
hints, not proof of callable Python bindings. Live checks remain necessary.

Avatar import accepts `.avt` through the native shim in **add mode**, preserving
the garment, and `.avac` through `ImportAVAC`. `apf_path` is supported only with `.avac`; invalid
combinations fail before import. Turntable output requires an image filename,
not a directory; it uses the working explicit-colorway overload. Tech pack output requires a `.json` filename and writes sidecars
alongside it. Its default `m_bSaveZprj`/`m_bSaveZpac` flags can change the active
project path; pass both as `false` to avoid those project saves.

Unknown export options are rejected before calling CLO. Native option values
must have the documented boolean/numeric types. Without the shim or constructible
Python option types, options cannot be used with dialog-only exports.

The shim defaults to macOS 15.0, matching the inspected SDK library. Override
`CMAKE_OSX_DEPLOYMENT_TARGET` only with a compatible SDK/runtime. Cross-architecture
builds can set `CMAKE_OSX_ARCHITECTURES`; host architecture is the default. Windows
symbol exports are configured for MSVC, but require a Windows build/load test.

See the [live test checklist](docs/live-test-checklist.md) for the prepared follow-up run and
[audit resolution record](docs/audit-fixes.md) for fixes and outstanding verification.
