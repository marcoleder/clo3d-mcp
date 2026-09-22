import json
import os
import sys
import time
import threading

# Shared transport has no third-party dependencies; CLO does not need mcp installed.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from clo3d_mcp.ipc import BridgeQueue, bridge_lock, comm_directory, atomic_json
from clo3d_mcp.contracts import FAILURE_FLAGS, OperationOutcomeUnknown, export_paths, same_project_path

try:
    import clo_shim as _clo_shim_mod
except Exception:            # never let the shim break the bridge
    _clo_shim_mod = None


def _shim():
    """The C++ shim if it loaded AND CLO's API pointers are live, else None."""
    if _clo_shim_mod is None:
        return None
    return _clo_shim_mod.load()


_IMPORT_ERROR = None
try:
    import export_api
    import fabric_api
    import import_api
    import pattern_api
    import utility_api
    IN_CLO3D = True
except ImportError as _e:
    IN_CLO3D = False
    _IMPORT_ERROR = str(_e)
    print("[CLO MCP] WARNING: Not running inside CLO3D. API calls will fail.")

# Communication directory
COMM_DIR = comm_directory()
POLL_INTERVAL = 0.1

# When CLO runs this from the Plugins menu, print() goes nowhere visible.
# Everything important is therefore also appended to a log file.
LOG_FILE = os.path.join(COMM_DIR, "bridge.log")


def log(msg):
    """Append a timestamped line to bridge.log; never raise."""
    line = time.strftime("%H:%M:%S ") + str(msg)
    print("[CLO MCP] " + str(msg))
    try:
        os.makedirs(COMM_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

_CLO_MCP_BRIDGE = True      # marker so a launcher can find prior instances
_server_running = False
_server_thread = None
_deadline = None


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_stop_bridge(params):
    global _server_running
    _server_running = False
    return {"stopped": True}


def handle_ping(params):
    return {"pong": True, "in_clo3d": IN_CLO3D}


# -- Scene --

def handle_debug_shim(params):
    """Report whether the C++ shim loaded and can see CLO's API pointers."""
    if _clo_shim_mod is None:
        return {"available": False, "reason": "clo_shim.py not importable"}
    st = _clo_shim_mod.status()
    st["active"] = _shim() is not None
    return st


def handle_debug_modules(params):
    """Exhaustive hunt for the option types + full module dumps.

    Earlier introspection checked only five modules and reported no classes,
    and binary strings include "ImportExportOption" and its field names.
    Strings alone do not establish Python registration; inspect reachable
    modules to gather runtime evidence.
    """
    import importlib

    found, dumps = [], {}
    names = ["export_api", "fabric_api", "import_api", "pattern_api",
             "utility_api", "rest_api"]
    for n in names:
        try:
            m = importlib.import_module(n)
        except Exception as e:
            dumps[n] = "IMPORT FAILED: %r" % (e,)
            continue
        attrs = sorted(a for a in dir(m) if not a.startswith("_"))
        types_ = []
        for a in attrs:
            try:
                v = getattr(m, a)
            except Exception:
                continue
            if isinstance(v, type):
                types_.append(a)
            if "option" in a.lower() or "Option" in a:
                found.append("%s.%s" % (n, a))
        dumps[n] = {"count": len(attrs), "types": types_, "all": attrs}

    # candidate module names the types might live in
    tried = {}
    for cand in ["CloApiData", "clo_api", "cloapi", "marvelous", "Marvelous",
                 "mv", "mv_api", "clo", "clo3d", "api", "common_api",
                 "avatar_api", "trim_api", "vmodule"]:
        try:
            m = importlib.import_module(cand)
            tried[cand] = sorted(a for a in dir(m) if not a.startswith("_"))[:40]
        except Exception as e:
            tried[cand] = "no: %s" % type(e).__name__

    return {"option_like_found": found, "modules": dumps,
            "candidate_imports": tried}


# commands that only read state — never worth a repaint
_READ_ONLY = {
    "ping", "stop_bridge", "get_project_info", "get_garment_info", "get_pattern_count",
    "get_pattern_list", "get_pattern_info", "get_pattern_bounding_box",
    "get_arrangement_list", "get_fabric_list", "get_fabric_count",
    "get_fabric_for_pattern", "get_colorways", "get_avatars",
    "get_avatar_genders", "get_bounding_box",
    "refresh_view", "set_live_preview",
    "debug_api", "debug_sig", "debug_modules", "debug_shim",
}

_LIVE_PREVIEW = {"enabled": False, "path": None}


def _snapshot_path():
    if not _LIVE_PREVIEW["path"]:
        import tempfile
        _LIVE_PREVIEW["path"] = os.path.join(
            tempfile.gettempdir(), "clo3d_live_preview.png")
    return _LIVE_PREVIEW["path"]


def _force_repaint():
    """Force the 3D viewport to actually redraw on screen.

    Measured on CLO 2026.1.224 with the bridge blocking the main thread:

      utility_api.Refresh3DWindow()   -> NO repaint. It posts an event, and a
                                         blocked event loop never handles it.
      export_api.ExportThumbnail3D()  -> NO repaint. Renders offscreen.
      export_api.ExportSnapshot3D()   -> REPAINTS. It captures the real
                                         viewport, so the viewport is drawn.

    So the only way to see progress live is to take a snapshot. It costs a
    render plus a ~1 MB PNG write (~0.3-0.5s), which is why it is opt-in.
    """
    utility_api.Refresh3DWindow()          # harmless; helps once unblocked
    try:
        export_api.ExportSnapshot3D(_snapshot_path())
        return True
    except Exception:
        return False


def handle_refresh_view(params):
    """Force the 3D viewport to redraw on screen.

    Refresh3DWindow alone does nothing while the bridge blocks CLO, so this
    also takes a snapshot, which does force a real repaint.
    """
    painted = _force_repaint()
    return {"refreshed": True, "repainted": painted,
            "snapshot": _snapshot_path() if painted else None}


def handle_set_live_preview(params):
    """Turn live preview on or off.

    When on, the bridge repaints the viewport after every state-changing
    command, so you can watch a batch happen instead of waiting for the end.
    Costs ~0.3-0.5s and a ~1 MB PNG per command.
    """
    _LIVE_PREVIEW["enabled"] = bool(params.get("enabled", True))
    if params.get("path"):
        _LIVE_PREVIEW["path"] = params["path"]
    return {"live_preview": _LIVE_PREVIEW["enabled"],
            "snapshot_path": _snapshot_path()}


def handle_debug_sig(params):
    """Return pybind11's full overload list for the given functions.

    Calling a pybind11 function with wrong args raises a TypeError whose text
    enumerates every signature it actually accepts. That is the ground truth
    for the Python binding, which need not match the C++ headers.
    """
    names = params.get("names") or [
        "ExportGLB", "ExportGLTF", "ExportFBX", "ExportTechPack",
        "ExportOBJ", "ExportThumbnail3D",
    ]
    out = {}
    for n in names:
        fn = getattr(export_api, n, None)
        if fn is None:
            out[n] = "NOT PRESENT on export_api"
            continue
        try:
            fn("__sig_probe__", "__sig_probe__", "__sig_probe__", "__sig_probe__")
            out[n] = "unexpectedly accepted 4 junk args"
        except TypeError as e:
            out[n] = str(e)
        except Exception as e:
            out[n] = type(e).__name__ + ": " + str(e)
    out["_export_api_dir"] = sorted(
        a for a in dir(export_api) if not a.startswith("_")
    )
    return out


def handle_debug_api(params):
    """Introspect the live CLO Python modules.

    Diagnostic only; deliberately not exposed as an MCP tool. Exists because
    the option structs (ImportExportOption / ExportTechpackOption) are required
    by ExportFBX/GLB/GLTF/TechPack but are not attributes of export_api, and
    static analysis of the SDK headers cannot reveal their bound Python name.
    """
    mods = {
        "export_api": export_api, "fabric_api": fabric_api,
        "import_api": import_api, "pattern_api": pattern_api,
        "utility_api": utility_api,
    }
    out = {}
    for name, m in mods.items():
        attrs = [a for a in dir(m) if not a.startswith("_")]
        classes, option_like = [], []
        for a in attrs:
            try:
                v = getattr(m, a)
            except Exception:
                continue
            if isinstance(v, type):
                classes.append(a)
            if "option" in a.lower():
                option_like.append(a)
        out[name] = {"total": len(attrs), "classes": classes,
                     "option_like": option_like}
    # also look for the types anywhere reachable
    found = []
    for modname, m in list(sys.modules.items()):
        if m is None:
            continue
        for want in ("ImportExportOption", "ExportTechpackOption"):
            if hasattr(m, want):
                found.append(modname + "." + want)
    out["_found_elsewhere"] = found
    out["_sys_modules_sample"] = sorted(
        n for n in sys.modules if "api" in n.lower() or "clo" in n.lower()
    )[:25]
    return out


def handle_get_project_info(params):
    name = utility_api.GetProjectName()
    path = utility_api.GetProjectFilePath()
    major = utility_api.GetMajorVersion()
    minor = utility_api.GetMinorVersion()
    patch = utility_api.GetPatchVersion()
    pattern_count = pattern_api.GetPatternCount()
    fabric_count = fabric_api.GetFabricCount(-2)
    colorway_count = utility_api.GetColorwayCount()
    return {
        "project_name": name,
        "project_path": path,
        "clo_version": str(major) + "." + str(minor) + "." + str(patch),
        "pattern_count": pattern_count,
        "fabric_count": fabric_count,
        "colorway_count": colorway_count,
    }


def handle_new_project(params):
    utility_api.NewProject()
    return {"created": True}


def _scene_signature():
    """Observable identity, deliberately excluding transient rendering data."""
    return {
        "project_path": utility_api.GetProjectFilePath(),
        "patterns": [pattern_api.GetPatternPieceName(i)
                     for i in range(pattern_api.GetPatternCount())],
        "avatars": export_api.GetAvatarCount(),
        "avatar_names": export_api.GetAvatarNameList(),
        "fabrics": fabric_api.GetFabricCount(-2),
        "colorways": utility_api.GetColorwayCount(),
    }


def _import_file_checked(file_path):
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)
    extension = os.path.splitext(file_path)[1].lower()
    # Generic ImportFile may replace the garment. Always use the dedicated
    # verified add route for avatar/fabric imports.
    if extension in (".avt", ".avac"):
        return handle_import_avatar({"file_path": file_path})
    if extension in (".zfab", ".jfab"):
        return handle_import_fabric({"file_path": file_path})
    before = utility_api.GetProjectFilePath()
    if extension == ".zprj" and same_project_path(before, file_path):
        if _review_required():
            raise RuntimeError("Restore a distinct .zprj backup to resolve the uncertain scene; "
                               "a reload of the active path cannot be verified")
        # Opening an already active project is an explicit no-op; it must not
        # pretend to reload unsaved edits via an unverifiable ImportFile call.
        return {"verified": True, "already_active": True}
    signature = _scene_signature() if extension != ".zprj" else None
    camera = utility_api.GetCustomViewInformation() if extension == ".zcmr" else None
    try:
        result = import_api.ImportFile(file_path)
        if not result:
            raise RuntimeError("ImportFile returned false")
        if extension == ".zprj":
            actual = utility_api.GetProjectFilePath()
            if not same_project_path(actual, file_path):
                raise RuntimeError("Requested project is not active after ImportFile: " + str(actual))
            _clear_review()
        elif (_scene_signature() == signature
              and (extension != ".zcmr" or utility_api.GetCustomViewInformation() == camera)):
            raise RuntimeError("ImportFile returned true without an observable scene change")
    except Exception as exc:
        raise OperationOutcomeUnknown(str(exc)) from exc
    return {"verified": True, "already_active": False}


def handle_open_file(params):
    file_path = params["file_path"]
    details = _import_file_checked(file_path)
    return dict(details, opened=True, file_path=file_path)


def handle_save_file(params):
    file_path = params["file_path"]
    result = export_api.ExportZPrj(file_path)
    return {"saved": bool(result), "file_path": result or file_path}


def handle_get_garment_info(params):
    info_str = export_api.ExportGarmentInformationToStream()
    if info_str:
        try:
            data = json.loads(info_str)
        except (json.JSONDecodeError, TypeError):
            data = {"raw": str(info_str)}
        return {"garment_info": data}
    return {"garment_info": None}


# -- Pattern --

def handle_get_pattern_count(params):
    count = pattern_api.GetPatternCount()
    return {"count": count}


def handle_get_pattern_list(params):
    count = pattern_api.GetPatternCount()
    patterns = []
    for i in range(count):
        name = pattern_api.GetPatternPieceName(i)
        patterns.append({"index": i, "name": name})
    return {"patterns": patterns, "count": count}


def handle_get_pattern_info(params):
    index = params["pattern_index"]
    info_str = pattern_api.GetPatternInformation(index)
    try:
        info = json.loads(info_str) if info_str else {}
    except (json.JSONDecodeError, TypeError):
        info = {"raw": str(info_str)}
    name = pattern_api.GetPatternPieceName(index)
    return {"index": index, "name": name, "info": info}


def handle_get_bounding_box(params):
    index = params["pattern_index"]
    bb = pattern_api.GetBoundingBoxOfPattern(index)
    return {"index": index, "bounding_box": bb}


def handle_set_pattern_name(params):
    index = params["pattern_index"]
    name = params["name"]
    pattern_api.SetPatternPieceName(index, name)
    return {"index": index, "name": name}


def handle_copy_pattern(params):
    index = params["pattern_index"]
    x = params.get("x", 0)
    y = params.get("y", 0)
    new_index = pattern_api.CopyPatternPieceMove(index, float(x), float(y))
    if new_index < 0:
        raise RuntimeError("CopyPatternPieceMove failed")
    return {"copied": True, "source_index": index, "new_index": new_index, "offset": [x, y]}


def handle_delete_pattern(params):
    index = params["pattern_index"]
    pattern_api.DeletePatternPiece(index)
    return {"deleted": True, "index": index}


def handle_flip_pattern(params):
    index = params["pattern_index"]
    horizontal = params.get("horizontal", True)
    each = params.get("each", True)
    pattern_api.FlipPatternPiece(index, horizontal, each)
    return {"flipped": True, "index": index, "horizontal": horizontal, "each": each}


def handle_create_pattern(params):
    points = params["points"]
    point_tuples = []
    for p in points:
        x, y = p[0], p[1]
        vtype = p[2] if len(p) > 2 else 0
        # CreatePatternWithPoints takes vector<tuple<float, float, int>>.
        # pybind11 invokes NESTED type casters with convert=False, so a Python
        # int in the x/y slots is rejected outright ("incompatible function
        # arguments") rather than promoted. Coerce explicitly.
        point_tuples.append((float(x), float(y), int(vtype)))
    count_before = pattern_api.GetPatternCount()
    result = pattern_api.CreatePatternWithPoints(point_tuples)
    if result < 0 or pattern_api.GetPatternCount() <= count_before:
        raise RuntimeError("CreatePatternWithPoints failed")
    return {"created": True, "point_count": len(point_tuples), "result": result}


def handle_get_arrangement_list(params):
    arr_list = pattern_api.GetArrangementList()
    return {"arrangements": arr_list}


# -- Fabric --

def handle_get_fabric_count(params):
    count = fabric_api.GetFabricCount(-2)
    return {"count": count}


def handle_get_fabric_list(params):
    count = fabric_api.GetFabricCount(-2)
    fabrics = []
    for i in range(count):
        fabrics.append({"index": i, "name": fabric_api.GetFabricName(i)})
    return {"fabrics": fabrics, "count": count}


def _add_fabric(file_path):
    before = fabric_api.GetFabricCount(-2)
    try:
        index = fabric_api.AddFabric(file_path)
        after = fabric_api.GetFabricCount(-2)
        if type(index) is not int or not 0 <= index < after or after <= before:
            raise RuntimeError("AddFabric did not return a valid new fabric")
        return index
    except Exception as exc:
        raise OperationOutcomeUnknown(str(exc)) from exc


def handle_add_fabric(params):
    file_path = params["file_path"]
    index = _add_fabric(file_path)
    return {"added": True, "fabric_index": index, "file_path": file_path}


def handle_assign_fabric(params):
    fabric_index = params["fabric_index"]
    pattern_index = params["pattern_index"]
    option = params.get("assign_option", 1)
    result = fabric_api.AssignFabricToPattern(fabric_index, pattern_index, option)
    return {"assigned": result, "fabric_index": fabric_index, "pattern_index": pattern_index}


def handle_set_fabric_color(params):
    fabric_index = params["fabric_index"]
    r = params.get("r", 255)
    g = params.get("g", 255)
    b = params.get("b", 255)
    a = params.get("a", 255)
    material_face = params.get("material_face", 0)
    # Convert 0-255 int range to 0.0-1.0 float range
    r_f = r / 255.0
    g_f = g / 255.0
    b_f = b / 255.0
    a_f = a / 255.0
    if not fabric_api.SetFabricPBRMaterialBaseColor(fabric_index, material_face, r_f, g_f, b_f, a_f):
        raise RuntimeError("SetFabricPBRMaterialBaseColor returned false")
    return {"set": True, "fabric_index": fabric_index, "color": [r, g, b, a]}


def handle_get_fabric_for_pattern(params):
    pattern_index = params["pattern_index"]
    fabric_index = fabric_api.GetFabricIndexForPattern(pattern_index)
    return {"pattern_index": pattern_index, "fabric_index": fabric_index}


def handle_replace_fabric(params):
    # fabric_api.ReplaceFabric(fabricIndex, inputFilePath) -> bool
    fabric_index = params["fabric_index"]
    file_path = params["file_path"]
    result = fabric_api.ReplaceFabric(fabric_index, file_path)
    return {"replaced": bool(result), "fabric_index": fabric_index,
            "file_path": file_path}


def handle_delete_fabric(params):
    fabric_index = params["fabric_index"]
    result = fabric_api.DeleteFabric(fabric_index)
    return {"deleted": result, "fabric_index": fabric_index}


# -- Export --

# CLO 2026.1.224 registers NO Python classes in any of its api modules
# (verified: dir() yields zero types in export/fabric/import/pattern/utility_api).
# pybind11 therefore reports the option parameters by their raw C++ name,
# "Marvelous::ImportExportOption", which is how it renders an UNREGISTERED type:
#
#   ExportGLB(): incompatible function arguments. The following argument
#   types are supported:
#       1. (arg0: str, arg1: Marvelous::ImportExportOption) -> List[str]
#
# There is no Python expression that can produce such a value, and ExportFBX /
# ExportGLB / ExportGLTF / ExportTechPack have no option-free overload. These
# four exports are therefore unreachable from CLO's Python at all. Only a C++
# plug-in, which can construct Marvelous::ImportExportOption directly, can call
# them. ExportOBJ is unaffected: it has an ExportOBJ(filePath) overload.
_NO_OPTION_TYPE = (
    "CLO {ver} does not expose Marvelous::{typ} to Python (it registers no "
    "classes at all), and {fn} has no option-free overload, so this export "
    "cannot be performed from the Python bridge. Use export_obj, or the "
    "dialog-based variant if one exists, or drive {fn} from a C++ plug-in."
)


def _clo_version():
    try:
        return "%s.%s.%s" % (utility_api.GetMajorVersion(),
                             utility_api.GetMinorVersion(),
                             utility_api.GetPatchVersion())
    except Exception:
        return "2026.1"


def _unsupported(fn, typ="ImportExportOption"):
    return RuntimeError(_NO_OPTION_TYPE.format(ver=_clo_version(), typ=typ, fn=fn))


def _build_export_option(options):
    """Return an ImportExportOption, or raise a clear error if impossible.

    Kept as a hook: if a future CLO registers the type, this starts working
    with no other change.
    """
    ctor = getattr(export_api, "ImportExportOption", None) or getattr(
        export_api, "NewImportExportOption", None)
    if ctor is None:
        raise _unsupported("ExportOBJ/FBX/GLB/GLTF")
    opt = ctor()
    for key, val in (options or {}).items():
        if not hasattr(opt, key):
            raise ValueError("Unsupported export option: " + key)
        setattr(opt, key, val)
    return opt


def handle_export_obj(params):
    file_path = params["file_path"]
    options = params.get("options", {})
    sh = _shim() if options else None
    if sh:
        paths, rejected = sh.export_obj(file_path, options)
        return {"exported": bool(paths), "file_paths": paths, "format": "obj",
                "via": "clo_shim", "rejected_options": rejected}
    if options:
        opt = _build_export_option(options)
        result = export_api.ExportOBJ(file_path, opt)
    else:
        result = export_api.ExportOBJ(file_path)
    # ExportOBJ returns list[str], not str
    if isinstance(result, list):
        exported = len(result) > 0
        file_paths = result
    else:
        exported = bool(result)
        file_paths = [result] if result else [file_path]
    return {"exported": exported, "file_paths": file_paths, "format": "obj"}


def handle_export_fbx(params):
    file_path = params["file_path"]
    sh = _shim()
    if sh:
        paths, rejected = sh.export_fbx(file_path, params.get("options"))
        return {"exported": bool(paths), "file_paths": paths, "format": "fbx",
                "via": "clo_shim", "rejected_options": rejected}
    options = _build_export_option(params.get("options"))
    result = export_api.ExportFBX(file_path, options)
    return {"exported": bool(result), "file_path": result or file_path, "format": "fbx"}


def handle_export_glb(params):
    file_path = params["file_path"]
    sh = _shim()
    if sh:
        paths, rejected = sh.export_glb(file_path, params.get("options"))
        return {"exported": bool(paths), "file_paths": paths, "format": "glb",
                "via": "clo_shim", "rejected_options": rejected}
    if hasattr(export_api, "ImportExportOption") or hasattr(export_api, "NewImportExportOption"):
        result = export_api.ExportGLB(file_path, _build_export_option(params.get("options")))
    elif not params.get("options") and hasattr(export_api, "ExportGLBWithDialog"):
        # opens CLO's export dialog; needs a human click but is the only
        # route available while the option type is unregistered
        result = export_api.ExportGLBWithDialog(file_path)
    else:
        raise _unsupported("ExportGLB")
    return {"exported": bool(result), "file_path": result or file_path, "format": "glb"}


def handle_export_gltf(params):
    file_path = params["file_path"]
    sh = _shim()
    if sh:
        paths, rejected = sh.export_gltf(file_path, params.get("options"), binary=False)
        return {"exported": bool(paths), "file_paths": paths, "format": "gltf",
                "via": "clo_shim", "rejected_options": rejected}
    if hasattr(export_api, "ImportExportOption") or hasattr(export_api, "NewImportExportOption"):
        result = export_api.ExportGLTF(
            file_path, _build_export_option(params.get("options")), False
        )
    elif not params.get("options") and hasattr(export_api, "ExportGLTFWithDialog"):
        result = export_api.ExportGLTFWithDialog(file_path, False)
    else:
        raise _unsupported("ExportGLTF")
    return {"exported": bool(result), "file_path": result or file_path, "format": "gltf"}


def handle_export_thumbnail(params):
    file_path = params["file_path"]
    result = export_api.ExportThumbnail3D(file_path)
    return {"exported": bool(result), "file_path": result or file_path}


def handle_export_snapshot(params):
    file_path = params["file_path"]
    # CLO returns vector<vector<string>> grouped by colorway/view.
    result = export_api.ExportSnapshot3D(file_path)
    paths = export_paths(result)
    if any(not os.path.isfile(path) or os.path.getsize(path) == 0 for path in paths):
        raise RuntimeError("CLO did not produce all snapshot files")
    # Preserve the historical SDK-shaped key while providing normalized paths.
    return {"exported": True, "file_paths": paths, "file_path": result}


def handle_export_turntable(params):
    file_path = params["file_path"]
    num_images = params.get("number_of_images", 36)
    width = params.get("width", 2500)
    height = params.get("height", 2500)
    if num_images <= 0 or width <= 0 or height <= 0:
        raise ValueError("Image count and dimensions must be positive")
    if os.path.splitext(file_path)[1].lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError("Turntable output must be an image filename, such as /output/view.png")
    # The ordinary path overload returns [] on 2026.1.224 in Python AND C++.
    # The explicit current-colorway overload produces the requested images.
    colorway = utility_api.GetCurrentColorwayIndex()
    result = export_api.ExportTurntableImagesByColorwayIndex(
        file_path, num_images, colorway, width, height)
    if not result:
        raise RuntimeError("CLO ExportTurntableImagesByColorwayIndex returned no images; turntable export failed")
    if len(result) != num_images or any(not os.path.isfile(p) for p in result):
        raise RuntimeError("CLO did not produce all requested turntable images")
    return {"exported": True, "file_paths": result,
            "number_of_images": num_images, "width": width, "height": height}


def _file_stamp(file_path):
    try:
        stat = os.stat(file_path)
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def _verify_techpack(file_path, before=None):
    if before is not None and _file_stamp(file_path) == before:
        raise RuntimeError("CLO did not update the existing tech pack")
    with open(file_path, encoding="utf-8") as stream:
        if not json.load(stream):
            raise RuntimeError("CLO produced an empty tech pack")


def handle_export_tech_pack(params):
    file_path = params["file_path"]
    # ExportTechPack returns void: verify the JSON artifact before reporting success.
    if os.path.splitext(file_path)[1].lower() != ".json":
        raise ValueError("Tech pack output must be a .json filename")
    before = _file_stamp(file_path)
    sh = _shim()
    if sh:
        rejected = sh.export_techpack(file_path, params.get("options"))
        _verify_techpack(file_path, before)
        return {"exported": True, "file_path": file_path,
                "via": "clo_shim", "rejected_options": rejected}
    if not hasattr(export_api, "ExportTechpackOption"):
        # ExportTechPack(str, ExportTechpackOption) is the only overload.
        # ExportTechPackToStream(str) exists and needs no option type, but it
        # returns the pack as a stream rather than writing file_path, so it is
        # not a drop-in substitute — surface the limitation instead.
        raise _unsupported("ExportTechPack", typ="ExportTechpackOption")
    opt = export_api.ExportTechpackOption()
    for key, value in params.get("options", {}).items():
        if not hasattr(opt, key):
            raise ValueError("Unsupported tech pack option: " + key)
        setattr(opt, key, value)
    export_api.ExportTechPack(file_path, opt)
    _verify_techpack(file_path, before)
    return {"exported": True, "file_path": file_path}


# -- Import --

def handle_import_file(params):
    file_path = params["file_path"]
    details = _import_file_checked(file_path)
    return dict(details, imported=True, file_path=file_path)


def handle_import_avatar(params):
    file_path = params["file_path"]
    apf_path = params.get("apf_path", "")
    extension = os.path.splitext(file_path)[1].lower()
    if extension not in (".avt", ".avac"):
        raise ValueError("Avatar file must be .avt or .avac")
    sh = None
    if extension == ".avt":
        if apf_path:
            raise ValueError("apf_path is supported only for .avac; import the .avt without it")
        sh = _shim()
        if sh is None or sh.abi < 2:
            raise RuntimeError("AVT import requires the updated native shim (ABI 2); build cpp/ first")
    before = export_api.GetAvatarCount()
    patterns = handle_get_pattern_list({})
    project = utility_api.GetProjectFilePath()
    try:
        result = (sh.import_avatar(file_path) if sh is not None
                  else import_api.ImportAVAC(file_path, apf_path))
        if not result or export_api.GetAvatarCount() <= before:
            raise RuntimeError("Avatar import did not add an avatar")
        if handle_get_pattern_list({}) != patterns or utility_api.GetProjectFilePath() != project:
            raise RuntimeError("Avatar import unexpectedly changed the garment or project")
    except Exception as exc:
        # No reliable avatar-delete/rollback API is available. Mark the outcome
        # as uncertain and block further mutations until a verified recovery.
        raise OperationOutcomeUnknown(str(exc)) from exc
    return {"imported": True, "file_path": file_path}


def handle_import_fabric(params):
    file_path = params["file_path"]
    index = _add_fabric(file_path)
    return {"imported": True, "fabric_index": index, "file_path": file_path}


# -- Simulation --

def handle_simulate(params):
    steps = params.get("steps", 100)
    if not utility_api.Simulate(steps):
        raise RuntimeError("Simulate returned false")
    return {"simulated": True, "steps": steps}


def handle_set_simulation_quality(params):
    # CLO 2026.1: SetSimulationQuality(quality, simulationMode) — both required.
    # quality: 0=Normal 1=Animation(Stable) 2=Fitting(Accurate) 3=FAST(GPU)
    # simulationMode: 0=CPU 1=FAST(GPU)
    quality = params["quality"]
    simulation_mode = params.get("simulation_mode", 0)
    utility_api.SetSimulationQuality(quality, simulation_mode)
    return {"quality": quality, "simulation_mode": simulation_mode}


# -- Colorway --

def handle_get_colorways(params):
    count = utility_api.GetColorwayCount()
    names = export_api.GetColorwayNameList()
    current = utility_api.GetCurrentColorwayIndex()
    colorways = []
    if names:
        for i, name in enumerate(names):
            colorways.append({"index": i, "name": name, "current": i == current})
    else:
        for i in range(count):
            colorways.append({"index": i, "current": i == current})
    return {"colorways": colorways, "count": count, "current_index": current}


def handle_set_current_colorway(params):
    index = params["colorway_index"]
    utility_api.SetCurrentColorwayIndex(index)
    return {"set": True, "colorway_index": index}


def handle_set_colorway_name(params):
    index = params["colorway_index"]
    name = params["name"]
    utility_api.SetColorwayName(index, name)
    return {"set": True, "colorway_index": index, "name": name}


def handle_copy_colorway(params):
    # CLO 2026.1: CopyColorway(index, copyOption) -> index of the new colorway.
    # copyOption: 0=unlink all properties 1=unlink materials only 2=link all
    index = params["colorway_index"]
    copy_option = params.get("copy_option", 0)
    new_index = utility_api.CopyColorway(index, copy_option)
    return {"copied": True, "source_index": index,
            "copy_option": copy_option, "new_index": new_index}


def handle_delete_colorway(params):
    index = params["colorway_index"]
    utility_api.DeleteColorwayItem(index)
    return {"deleted": True, "colorway_index": index}


# -- Avatar --

def handle_get_avatars(params):
    count = export_api.GetAvatarCount()
    names = export_api.GetAvatarNameList()
    genders = export_api.GetAvatarGenderList()
    avatars = []
    if names:
        for i, name in enumerate(names):
            avatar = {"index": i, "name": name}
            if genders and i < len(genders):
                avatar["gender"] = genders[i]
            avatars.append(avatar)
    return {"avatars": avatars, "count": count}


def handle_show_hide_avatar(params):
    show = params.get("show", True)
    utility_api.SetShowHideAvatar(show)
    return {"visible": show}


def handle_get_avatar_genders(params):
    genders = export_api.GetAvatarGenderList()
    return {"genders": genders or []}


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

HANDLERS = {
    "ping": handle_ping,
    "stop_bridge": handle_stop_bridge,
    "debug_api": handle_debug_api,
    "debug_sig": handle_debug_sig,
    "debug_modules": handle_debug_modules,
    "debug_shim": handle_debug_shim,
    "refresh_view": handle_refresh_view,
    "set_live_preview": handle_set_live_preview,
    "get_project_info": handle_get_project_info,
    "new_project": handle_new_project,
    "open_file": handle_open_file,
    "save_file": handle_save_file,
    "get_garment_info": handle_get_garment_info,
    "get_pattern_count": handle_get_pattern_count,
    "get_pattern_list": handle_get_pattern_list,
    "get_pattern_info": handle_get_pattern_info,
    "get_bounding_box": handle_get_bounding_box,
    "set_pattern_name": handle_set_pattern_name,
    "copy_pattern": handle_copy_pattern,
    "delete_pattern": handle_delete_pattern,
    "flip_pattern": handle_flip_pattern,
    "create_pattern": handle_create_pattern,
    "get_arrangement_list": handle_get_arrangement_list,
    "get_fabric_count": handle_get_fabric_count,
    "get_fabric_list": handle_get_fabric_list,
    "add_fabric": handle_add_fabric,
    "assign_fabric": handle_assign_fabric,
    "set_fabric_color": handle_set_fabric_color,
    "get_fabric_for_pattern": handle_get_fabric_for_pattern,
    "replace_fabric": handle_replace_fabric,
    "delete_fabric": handle_delete_fabric,
    "export_obj": handle_export_obj,
    "export_fbx": handle_export_fbx,
    "export_glb": handle_export_glb,
    "export_gltf": handle_export_gltf,
    "export_thumbnail": handle_export_thumbnail,
    "export_snapshot": handle_export_snapshot,
    "export_turntable": handle_export_turntable,
    "export_tech_pack": handle_export_tech_pack,
    "import_file": handle_import_file,
    "import_avatar": handle_import_avatar,
    "import_fabric": handle_import_fabric,
    "simulate": handle_simulate,
    "set_simulation_quality": handle_set_simulation_quality,
    "get_colorways": handle_get_colorways,
    "set_current_colorway": handle_set_current_colorway,
    "set_colorway_name": handle_set_colorway_name,
    "copy_colorway": handle_copy_colorway,
    "delete_colorway": handle_delete_colorway,
    "get_avatars": handle_get_avatars,
    "show_hide_avatar": handle_show_hide_avatar,
    "get_avatar_genders": handle_get_avatar_genders,
}


# ---------------------------------------------------------------------------
# File-based communication
# ---------------------------------------------------------------------------

def _review_file():
    return os.path.join(COMM_DIR, "scene-review-required.json")


def _review_required():
    # Existence is fail-closed even if an interrupted write/corruption lost details.
    return os.path.exists(_review_file())


def _clear_review():
    if _review_required():
        os.remove(_review_file())


def _is_recovery(command, params):
    return command in ("open_file", "import_file") and os.path.splitext(
        str(params.get("file_path", "")))[1].lower() == ".zprj"


def process_command(data):
    """Parse and execute a single JSON command."""
    try:
        request = json.loads(data)
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({"id": None, "status": "error", "message": "Invalid JSON: " + str(e)})

    if not isinstance(request, dict):
        return json.dumps({"id": None, "status": "error", "message": "Request must be an object"})
    req_id = request.get("id")
    cmd_type = request.get("type")
    params = request.get("params", {})

    if not isinstance(cmd_type, str) or not isinstance(params, dict):
        return json.dumps({"id": req_id, "status": "error", "message": "Invalid command or parameters"})
    handler = HANDLERS.get(cmd_type)
    if not handler:
        return json.dumps({
            "id": req_id,
            "status": "error",
            "message": "Unknown command: " + str(cmd_type),
        })

    try:
        if _review_required() and cmd_type not in _READ_ONLY and not _is_recovery(cmd_type, params):
            raise OperationOutcomeUnknown("A previous mutation needs scene review. "
                                          "Inspect CLO and restore a distinct .zprj backup before more mutations")
        result = handler(params)
        for flag in FAILURE_FLAGS:
            if result.get(flag) is False:
                raise RuntimeError(cmd_type + " reported " + flag + "=false")
        # With live preview on, force the viewport to redraw after anything
        # that changed state, so a batch can be watched as it happens.
        if _LIVE_PREVIEW["enabled"] and cmd_type not in _READ_ONLY:
            try:
                _force_repaint()
            except Exception:
                pass          # a preview failure must never fail the command
        return json.dumps({"id": req_id, "status": "success", "result": result})
    except Exception as e:
        response = {"id": req_id, "status": "error",
                    "message": str(type(e).__name__) + ": " + str(e)}
        if isinstance(e, OperationOutcomeUnknown):
            response.update(outcome="unknown", retry_safe=False, scene_review_required=True)
            if not _review_required():
                atomic_json(_review_file(), {"command": cmd_type, "id": req_id, "reason": str(e)})
        return json.dumps(response)


def poll_loop():
    """Serve one command at a time on the calling thread."""
    global _server_running
    with bridge_lock(COMM_DIR):
        queue = BridgeQueue(COMM_DIR)
        stop_file = os.path.join(COMM_DIR, "stop")
        if os.path.exists(stop_file):
            os.remove(stop_file)
        queue.start()
        log("protocol 2 ready in " + COMM_DIR)
        try:
            while _server_running:
                if _deadline is not None and time.time() >= _deadline:
                    log("deadline reached; stopping between commands")
                    break
                if os.path.exists(stop_file):
                    os.remove(stop_file)
                    break
                if not queue.process_one(process_command):
                    time.sleep(POLL_INTERVAL)
        finally:
            queue.close()
            _server_running = False
            log("poll_loop stopped")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start():
    """Start the MCP plugin."""
    global _server_running, _server_thread

    if _server_running:
        log("already running")
        return

    _server_running = True
    _server_thread = threading.Thread(target=poll_loop, daemon=True)
    _server_thread.start()
    log("bridge started")


def stop():
    """Stop the MCP plugin."""
    global _server_running, _server_thread

    if not _server_running:
        print("[CLO MCP] Not running")
        return

    _server_running = False
    if _server_thread:
        _server_thread.join(timeout=5)
        _server_thread = None
    print("[CLO MCP] Plugin stopped")


def run_blocking(duration_seconds=600):
    """Run the poll loop on the CALLING thread for a bounded time.

    CLO's embedded Python does not schedule background threads: once a plug-in
    script returns, the interpreter is not re-entered, so a daemon thread never
    gets the GIL and silently stops serving requests.

    This runs the loop inline instead. CLO's UI is unresponsive for the
    duration. The deadline and stop requests are checked BETWEEN commands;
    they cannot interrupt a native call or dismiss a modal dialog.
    """
    global _server_running, _deadline
    _deadline = time.time() + duration_seconds
    _server_running = True
    log("run_blocking for %ss (UI will be unresponsive)" % duration_seconds)
    try:
        poll_loop()
    finally:
        _server_running = False
        _deadline = None
        log("run_blocking finished")


# Auto-start.
# Executing this file is always an explicit request to start the bridge, so do
# not gate it on __name__ or IN_CLO3D: when CLO runs a plug-in from the Plugins
# menu, __name__ is not "__main__", and gating on it silently did nothing.
# Imported by a launcher (e.g. start_bridge_blocking.py) -> do not auto-start;
# the launcher decides which mode to run. Executed by CLO as a plug-in script
# (__name__ == "__main__") -> start.
_IMPORTED_AS_MODULE = __name__ == "clo3d_mcp_plugin"

log("--- script executed: __name__=%r IN_CLO3D=%s ---" % (__name__, IN_CLO3D))
if _IMPORT_ERROR:
    log("CLO API import failed: " + _IMPORT_ERROR)
if _IMPORTED_AS_MODULE:
    log("imported as a module; launcher chooses the run mode")
else:
    try:
        start()
        log("start() returned; thread alive=%s" % (
            _server_thread.is_alive() if _server_thread else None))
    except Exception as _exc:
        log("start() raised: %r" % (_exc,))
        raise
