"""ctypes wrapper around the clo_shim native library.

Gives the Python bridge access to the CLO exports that CLO's own Python
bindings cannot reach — ExportFBX / ExportGLB / ExportGLTF / ExportTechPack,
export *options* for all of them, and AVT import in add mode (ABI 2).
See cpp/clo_shim.cpp for why.

Import is always safe: if the library is missing or not loadable, `load()`
returns None and callers fall back to whatever Python can still do.
"""

import ctypes
import os
import sys

_shim = None          # cached ready CloShim; transient failures are not cached
_load_errors = []


def _lib_names():
    """Library filename per platform, most likely first."""
    if sys.platform == "darwin":
        return ["libclo_shim_v2.dylib", "libclo_shim.dylib"]
    if sys.platform.startswith("win"):
        # MSVC emits clo_shim_v2.dll; MinGW may prefix with lib
        return ["clo_shim_v2.dll", "libclo_shim_v2.dll", "clo_shim.dll", "libclo_shim.dll"]
    return ["libclo_shim_v2.so", "libclo_shim.so"]


def _candidate_paths():
    """Where to look, in order. CLO_SHIM_PATH always wins."""
    env = os.environ.get("CLO_SHIM_PATH")
    if env:
        return [env]
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [
        os.path.join(os.path.dirname(here), "cpp", "build"),            # single-config
        os.path.join(os.path.dirname(here), "cpp", "build", "Release"),  # MSVC
        here,                                                            # beside the plugin
    ]
    # Prefer ABI-2 names across all folders before considering legacy names.
    return [os.path.join(r, n) for n in _lib_names() for r in roots]


def _default_path():
    for p in _candidate_paths():
        if os.path.exists(p):
            return p
    return _candidate_paths()[0]


class CloShim(object):
    """Thin, explicit binding. Every call checks `ready` first."""

    #: buffer for returned path lists; CLO can emit many texture paths
    BUF = 64 * 1024

    def __init__(self, path=None):
        self.path = path or os.environ.get("CLO_SHIM_PATH") or _default_path()
        self.lib = ctypes.CDLL(self.path)
        L = self.lib

        L.clo_shim_ready.argtypes = []
        L.clo_shim_ready.restype = ctypes.c_int
        L.clo_shim_abi_version.argtypes = []
        L.clo_shim_abi_version.restype = ctypes.c_int
        self._abi = int(L.clo_shim_abi_version())
        if self._abi not in (1, 2):
            raise RuntimeError("Unsupported clo_shim ABI: %s" % self._abi)
        if self._abi >= 2 and not hasattr(L, "clo_import_avatar"):
            raise RuntimeError("ABI-2 clo_shim is missing clo_import_avatar")

        L.clo_opts_create.restype = ctypes.c_void_p
        L.clo_opts_free.argtypes = [ctypes.c_void_p]
        L.clo_opts_set_bool.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        L.clo_opts_set_bool.restype = ctypes.c_int
        L.clo_opts_set_int.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        L.clo_opts_set_int.restype = ctypes.c_int
        L.clo_opts_set_float.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_float]
        L.clo_opts_set_float.restype = ctypes.c_int

        L.clo_tp_opts_create.restype = ctypes.c_void_p
        L.clo_tp_opts_free.argtypes = [ctypes.c_void_p]
        L.clo_tp_opts_set_bool.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        L.clo_tp_opts_set_bool.restype = ctypes.c_int

        for fn in ("clo_export_glb", "clo_export_fbx", "clo_export_obj"):
            f = getattr(L, fn)
            f.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            f.restype = ctypes.c_int
        L.clo_export_gltf.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_char_p, ctypes.c_int]
        L.clo_export_gltf.restype = ctypes.c_int
        L.clo_export_techpack.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        L.clo_export_techpack.restype = ctypes.c_int
        if hasattr(L, "clo_import_avatar"):
            L.clo_import_avatar.argtypes = [ctypes.c_char_p]
            L.clo_import_avatar.restype = ctypes.c_int

    # ------------------------------------------------------------------ state

    @property
    def ready(self):
        """True only when CLO's API pointers are live in this process."""
        try:
            return bool(self.lib.clo_shim_ready())
        except Exception:
            return False

    @property
    def abi(self):
        return self._abi

    # ---------------------------------------------------------------- options

    _BOOLS = {
        "bExportGarment", "bExportAvatar", "bSingleObject", "bThin",
        "bIncludeHiddenObject", "bIncludeInnerShape", "bSaveColorWays",
        "bSaveInZip", "bInvertX", "bInvertY", "bInvertZ",
    }
    _INTS = {"weldType", "axisX", "axisY", "axisZ"}
    _FLOATS = {"scale"}

    def _make_opts(self, options):
        """Build an ImportExportOption handle. Returns (handle, rejected_keys)."""
        h = self.lib.clo_opts_create()
        if not h:
            raise MemoryError("clo_opts_create failed")
        try:
            for k, v in (options or {}).items():
                key = k.encode("utf-8")
                if k in self._BOOLS and isinstance(v, bool):
                    ok = self.lib.clo_opts_set_bool(h, key, int(v))
                elif k in self._INTS and type(v) is int:
                    ok = self.lib.clo_opts_set_int(h, key, v)
                elif k in self._FLOATS and type(v) in (int, float):
                    ok = self.lib.clo_opts_set_float(h, key, float(v))
                else:
                    ok = 0
                if not ok:
                    raise ValueError("Unsupported export option or value: " + k)
            return h, []
        except Exception:
            self.lib.clo_opts_free(h)
            raise

    # ---------------------------------------------------------------- exports

    def _run(self, call, opts_handle):
        buf = ctypes.create_string_buffer(self.BUF)
        n = call(buf, self.BUF)
        if n == -2:
            raise RuntimeError("clo_shim: CLO API not available in this process")
        if n == -1:
            raise RuntimeError("clo_shim: output buffer too small")
        text = buf.value.decode("utf-8", "replace")
        return [p for p in text.split("\n") if p]

    def _export(self, cfn, file_path, options, extra=()):
        h, rejected = self._make_opts(options)
        try:
            paths = self._run(
                lambda b, n: cfn(file_path.encode("utf-8"), h, *(list(extra) + [b, n])), h)
        finally:
            self.lib.clo_opts_free(h)
        return paths, rejected

    def export_glb(self, file_path, options=None):
        return self._export(self.lib.clo_export_glb, file_path, options)

    def export_fbx(self, file_path, options=None):
        return self._export(self.lib.clo_export_fbx, file_path, options)

    def export_obj(self, file_path, options=None):
        return self._export(self.lib.clo_export_obj, file_path, options)

    def export_gltf(self, file_path, options=None, binary=False):
        return self._export(self.lib.clo_export_gltf, file_path, options,
                            extra=(1 if binary else 0,))

    def import_avatar(self, file_path):
        if self.abi < 2 or not hasattr(self.lib, "clo_import_avatar"):
            raise RuntimeError("AVT import requires shim ABI 2; rebuild cpp/ and restart the bridge")
        result = self.lib.clo_import_avatar(file_path.encode("utf-8"))
        if result < 0:
            raise RuntimeError("clo_shim: native avatar import failed (%s)" % result)
        return bool(result)

    def export_techpack(self, file_path, options=None):
        h = self.lib.clo_tp_opts_create()
        if not h:
            raise MemoryError("clo_tp_opts_create failed")
        rejected = []
        try:
            for k, v in (options or {}).items():
                if not isinstance(v, bool) or not self.lib.clo_tp_opts_set_bool(h, k.encode("utf-8"), int(v)):
                    raise ValueError("Unsupported tech pack option or value: " + k)
            rc = self.lib.clo_export_techpack(file_path.encode("utf-8"), h)
        finally:
            self.lib.clo_tp_opts_free(h)
        if rc == -2:
            raise RuntimeError("clo_shim: CLO API not available in this process")
        # ExportTechPack returns void: rc 0 means "no exception", not "verified"
        return rejected


def load(path=None):
    """Return the highest supported, ready ABI. Respect explicit paths.

    ABI 1 remains usable for exports; AVT requires ABI 2. A failed or not-yet-
    ready candidate cannot mask a working later candidate, and failures are
    retried on the next call. A cached ABI 1 is rescanned for upgrades.
    """
    global _shim, _load_errors
    explicit = path or os.environ.get("CLO_SHIM_PATH")
    if (_shim is not None and _shim.abi == 2 and _shim.ready
            and (not explicit or os.path.abspath(explicit) == os.path.abspath(_shim.path))):
        return _shim
    candidates = [explicit] if explicit else _candidate_paths()
    best = None
    _load_errors = []
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        try:
            loaded = CloShim(candidate)
            if not loaded.ready:
                raise RuntimeError("CLO API pointers are not ready")
            if best is None or loaded.abi > best.abi:
                best = loaded
            if loaded.abi == 2:
                break
        except Exception as exc:
            _load_errors.append({"path": candidate, "error": str(exc)})
    _shim = best
    return best


def status():
    """Report the selected library and rejected candidates, not just the first file."""
    selected = load()
    path = selected.path if selected is not None else _default_path()
    return {"path": path, "exists": os.path.exists(path), "platform": sys.platform,
            "searched": _candidate_paths(), "loaded": selected is not None,
            "ready": selected.ready if selected else False,
            "abi": selected.abi if selected else None, "errors": list(_load_errors)}
