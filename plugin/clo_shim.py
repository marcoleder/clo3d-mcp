"""ctypes wrapper around the clo_shim native library.

Gives the Python bridge access to the CLO exports that CLO's own Python
bindings cannot reach — ExportFBX / ExportGLB / ExportGLTF / ExportTechPack,
and export *options* for all of them. See cpp/clo_shim.cpp for why.

Import is always safe: if the library is missing or not loadable, `load()`
returns None and callers fall back to whatever Python can still do.
"""

import ctypes
import os
import sys

_shim = None          # cached CloShim, or False once a load has failed


def _lib_names():
    """Library filename per platform, most likely first."""
    if sys.platform == "darwin":
        return ["libclo_shim.dylib"]
    if sys.platform.startswith("win"):
        # MSVC emits clo_shim.dll; MinGW may prefix with lib
        return ["clo_shim.dll", "libclo_shim.dll"]
    return ["libclo_shim.so"]


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
    return [os.path.join(r, n) for r in roots for n in _lib_names()]


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

        L.clo_shim_ready.restype = ctypes.c_int
        L.clo_shim_abi_version.restype = ctypes.c_int

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
        return int(self.lib.clo_shim_abi_version())

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
    """Return a working CloShim, or None. Never raises."""
    global _shim
    if _shim is False:
        return None
    if _shim is not None and path is None:
        return _shim
    try:
        s = CloShim(path)
        if not s.ready:
            # loaded, but CLO's API pointers are empty — wrong process, or the
            # shim resolved a second copy of libCLOAPIInterface
            _shim = False
            return None
        _shim = s
        return s
    except Exception:
        _shim = False
        return None


def status():
    """Diagnostic detail for the bridge's debug commands."""
    p = _default_path()
    info = {"path": p, "exists": os.path.exists(p),
            "platform": sys.platform,
            "searched": _candidate_paths()}
    try:
        s = CloShim(p)
        info["loaded"] = True
        info["ready"] = s.ready
        info["abi"] = s.abi
    except Exception as e:
        info["loaded"] = False
        info["error"] = "%s: %s" % (type(e).__name__, e)
    return info
