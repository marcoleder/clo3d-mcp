# CLO3D MCP Server

Talk to CLO3D from Claude, Cursor, or any MCP client. Create patterns, swap fabrics, run simulations, export models. All from a chat window.

```
Your AI assistant  <-->  MCP Server  <-->  CLO3D Plugin  <-->  CLO3D
```

> **This is a fork** of [Ubani-Studio/clo3d-mcp](https://github.com/Ubani-Studio/clo3d-mcp),
> fixed and extended for **CLO 2026.1** on **macOS / Apple Silicon**.
> The bug fixes are offered upstream in [PR #2](https://github.com/Ubani-Studio/clo3d-mcp/pull/2);
> the rest lives here. See [what this fork changes](#what-this-fork-changes).

---

## Requirements

| | |
|---|---|
| CLO3D | **2026.1** (tested against 2026.1.224) |
| Python | 3.10+ for the MCP server (CLO ships its own 3.11 for the plug-in) |
| OS | macOS (Apple Silicon) tested end to end. Windows should work but is **untested** — see [Platform support](#platform-support) |
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
<summary>Script Editor instead (works on Windows, <b>not</b> on macOS)</summary>

**Script ▸ Script Editor ▸** open `plugin/clo3d_mcp_plugin.py` **▸ Run**.

This starts the bridge on a background thread. On macOS that thread **starves**:
CLO never re-enters Python after a plug-in script returns, so it never gets the
GIL. It reports `alive=True` while serving nothing. Use the menu item above.
</details>

## 3. Connect your MCP client

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

Set `CLO3D_MCP_DIR` in the client's `env` only if you need a non-default comm
directory; both sides default to `<temp>/clo3d_mcp`.

## 4. Run it

1. In CLO: **Plugins ▸ Plug-in ▸ MCP Bridge (serve)**
2. **CLO's UI freezes. That is expected** — see [How it works](#how-it-works)
3. Ask your assistant for something
4. The bridge releases automatically when the client finishes, or after its
   deadline

Try:
- *"What patterns are in this project?"*
- *"Set the front bodice fabric to red, then simulate 100 steps"*
- *"Export this as GLB without the avatar"*

**Call `ping` first if anything hangs.** The file IPC has a 180-second timeout,
so "the bridge isn't running" and "CLO is busy" look identical without it.

---

## The 47 tools

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

**Avatars** — `get_avatars` `get_avatar_genders` `show_hide_avatar` `import_avatar`

**Simulation** — `simulate` `set_simulation_quality`

**Export** — `export_obj` `export_fbx`\* `export_glb`\* `export_gltf`\*
`export_thumbnail` `export_snapshot` `export_turntable` `export_tech_pack`\*

**Import** — `import_file`

**Session** — `ping` `refresh_view` `set_live_preview`

\* needs the [native shim](#optional-native-shim). Export *options* on any
export also need it.

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

Four exports — **FBX, GLB, glTF and tech pack** — plus *export options* on all
of them are **impossible from CLO's Python**. They require
`Marvelous::ImportExportOption`, and CLO registers no Python classes at all.

A small C library fixes this. Without it those four tools return a clear error;
everything else works.

```bash
cd cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCLO_SDK_DIR=/path/to/CLO_SDK
cmake --build build --config Release
```

The plug-in picks it up automatically. It links **no Qt** and needs no install
step. See [`cpp/clo_shim.cpp`](cpp/clo_shim.cpp) for how it reaches CLO's own
API pointers.

---

## How it works

**The plug-in** (`plugin/clo3d_mcp_plugin.py`) runs inside CLO3D, polling a
shared directory for JSON commands and calling CLO's Python API.

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
sentinel, so CLO can never be wedged permanently.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Every tool times out after 180s | The bridge isn't running. Call `ping`. |
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
| MCP server + 47 tools | ✅ tested | should work, untested |
| Menu-item bridge | ✅ tested | should work, untested |
| Script Editor bridge | ❌ thread starves | likely works (upstream's route) |
| Native shim | ✅ tested | builds via MSVC, untested |
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
uv sync --dev
uv run pytest tests/ -v                     # no CLO needed

python3 tools/verify_against_clo.py         # static checks: wiring, arity, returns
python3 tools/live_test.py garment.zprj     # all 47 tools against a real garment
python3 tools/dialog_watcher.py 600 &       # auto-confirm CLO dialogs (macOS)
```

`verify_against_clo.py` parses the CLO SDK headers and checks every `*_api.X`
call for existence, arity (honouring C++ default arguments) and misused void
returns, plus handler↔tool wiring in both directions. Run it after any CLO or
SDK update.

---

## License

MIT for the code authored here. See [LICENSE](LICENSE).

`sdk/` holds CLO Virtual Fashion's interface headers and sample sources and is
**not** covered by that licence: no rights in it are granted here. See
[NOTICE](NOTICE). You need your own CLO3D licence.
