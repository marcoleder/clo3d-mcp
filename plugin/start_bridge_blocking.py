"""Menu launcher: run the MCP bridge inline on CLO's main thread.

Why inline: CLO's embedded Python does not schedule background threads. Once a
plug-in script returns, the interpreter is not re-entered, so a daemon thread
never gets the GIL and silently stops serving requests.

Why this file is careful about earlier runs: a starved background thread is not
dead, only unscheduled. As soon as an inline loop calls time.sleep() the GIL is
released and that old thread wakes up inside module state CLO may have torn
down, with two poll loops racing on the same files. Any previous instance is
therefore stopped through *its own* module object before a new one starts.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _retire_previous_instances():
    """Halt any bridge loop left over from an earlier run in this CLO session."""
    retired = []
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        if getattr(mod, "_CLO_MCP_BRIDGE", False) or name == "clo3d_mcp_plugin":
            # set the flag on the module the old thread is actually reading
            if getattr(mod, "_server_running", False):
                mod._server_running = False
                retired.append(name)
            sys.modules.pop(name, None)
    if retired:
        # give the woken thread a slice to observe the flag and exit its loop
        time.sleep(0.5)
    return retired


retired = _retire_previous_instances()
# Reload pure Python code on a menu restart. A replaced native dylib may still
# require restarting CLO because the OS caches loaded library images.
for name in ("clo_shim", "clo3d_mcp.ipc", "clo3d_mcp.contracts"):
    sys.modules.pop(name, None)

import clo3d_mcp_plugin as bridge  # noqa: E402  (must follow the cleanup above)

if retired:
    bridge.log("retired previous bridge instance(s): %s" % ", ".join(retired))

bridge.run_blocking(900)
