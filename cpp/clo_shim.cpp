// clo_shim — a C ABI over the handful of CLO APIs Python cannot reach.
//
// Why this exists
// ---------------
// ExportFBX / ExportGLB / ExportGLTF / ExportTechPack each require a
// Marvelous::ImportExportOption or ExportTechpackOption parameter, and CLO
// 2026.1.224 registers NO Python classes at all (verified: dir() yields zero
// types across export_api, fabric_api, import_api, pattern_api, utility_api
// and rest_api). pybind11 reports the parameter under its raw C++ name —
// "Marvelous::ImportExportOption" — which is how it renders an unregistered
// type. No Python expression can produce such a value, and none of those four
// functions has an option-free overload. They are unreachable from Python.
//
// How it works
// ------------
// CLOAPI::APICommand is a singleton whose getInstance() and _instance symbols
// are exported from libCLOAPIInterface.dylib — the copy CLO already has
// loaded. Because this shim links that same dylib by
// @executable_path/../Frameworks/libCLOAPIInterface.dylib, dlopen()ing it from
// CLO's embedded Python (via ctypes) resolves to the SAME instance, already
// populated by CLO. So EXPORT_API / UTILITY_API are live here.
//
// Deliberately does NOT link Qt: nothing here needs it, and avoiding it means
// this library never needs retarget-qt.sh.

#include "CLOAPIInterface.h"

#include <cstring>
#include <string>
#include <vector>

using Marvelous::ExportTechpackOption;
using Marvelous::ImportExportOption;

namespace {

// Join result paths into caller-provided storage. Returns the number of paths,
// or -1 if the buffer was too small (caller can retry with a bigger one).
int writePaths(const std::vector<std::string>& paths, char* out, int outLen) {
    if (!out || outLen <= 0) return static_cast<int>(paths.size());
    std::string joined;
    for (size_t i = 0; i < paths.size(); ++i) {
        if (i) joined += '\n';
        joined += paths[i];
    }
    if (static_cast<int>(joined.size()) + 1 > outLen) {
        out[0] = '\0';
        return -1;
    }
    std::memcpy(out, joined.c_str(), joined.size() + 1);
    return static_cast<int>(paths.size());
}

ImportExportOption* opts(void* h) { return static_cast<ImportExportOption*>(h); }
ExportTechpackOption* tpOpts(void* h) { return static_cast<ExportTechpackOption*>(h); }

bool eq(const char* a, const char* b) { return std::strcmp(a, b) == 0; }

}  // namespace

extern "C" {

// ---------------------------------------------------------------- lifecycle

// 1 when CLO's API pointers are live in this process. Always check first:
// a 0 here means the shim was loaded outside CLO, or too early.
int clo_shim_ready() {
    return (EXPORT_API != nullptr && UTILITY_API != nullptr) ? 1 : 0;
}

int clo_shim_abi_version() { return 1; }

// ------------------------------------------------------- ImportExportOption

void* clo_opts_create() { return new (std::nothrow) ImportExportOption(); }
void clo_opts_free(void* h) { delete opts(h); }

// Returns 1 if the field was recognised and set, 0 otherwise. Unknown names
// are reported rather than silently ignored — silently dropping caller options
// is a bug this project has already been bitten by.
int clo_opts_set_bool(void* h, const char* name, int v) {
    ImportExportOption* o = opts(h);
    if (!o || !name) return 0;
    const bool b = v != 0;
    if (eq(name, "bExportGarment"))       { o->bExportGarment = b;       return 1; }
    if (eq(name, "bExportAvatar"))        { o->bExportAvatar = b;        return 1; }
    if (eq(name, "bSingleObject"))        { o->bSingleObject = b;        return 1; }
    if (eq(name, "bThin"))                { o->bThin = b;                return 1; }
    if (eq(name, "bIncludeHiddenObject")) { o->bIncludeHiddenObject = b; return 1; }
    if (eq(name, "bIncludeInnerShape"))   { o->bIncludeInnerShape = b;   return 1; }
    if (eq(name, "bSaveColorWays"))       { o->bSaveColorWays = b;       return 1; }
    if (eq(name, "bSaveInZip"))           { o->bSaveInZip = b;           return 1; }
    if (eq(name, "bInvertX"))             { o->bInvertX = b;             return 1; }
    if (eq(name, "bInvertY"))             { o->bInvertY = b;             return 1; }
    if (eq(name, "bInvertZ"))             { o->bInvertZ = b;             return 1; }
    return 0;
}

int clo_opts_set_int(void* h, const char* name, int v) {
    ImportExportOption* o = opts(h);
    if (!o || !name) return 0;
    if (eq(name, "weldType")) { o->weldType = static_cast<Marvelous::WELD_TYPE>(v); return 1; }
    if (eq(name, "axisX"))    { o->axisX = v; return 1; }
    if (eq(name, "axisY"))    { o->axisY = v; return 1; }
    if (eq(name, "axisZ"))    { o->axisZ = v; return 1; }
    return 0;
}

int clo_opts_set_float(void* h, const char* name, float v) {
    ImportExportOption* o = opts(h);
    if (!o || !name) return 0;
    if (eq(name, "scale")) { o->scale = v; return 1; }
    return 0;
}

// ----------------------------------------------------- ExportTechpackOption

void* clo_tp_opts_create() { return new (std::nothrow) ExportTechpackOption(); }
void clo_tp_opts_free(void* h) { delete tpOpts(h); }

int clo_tp_opts_set_bool(void* h, const char* name, int v) {
    ExportTechpackOption* o = tpOpts(h);
    if (!o || !name) return 0;
    const bool b = v != 0;
    if (eq(name, "m_bSaveZprj"))               { o->m_bSaveZprj = b;               return 1; }
    if (eq(name, "m_bSaveZpac"))               { o->m_bSaveZpac = b;               return 1; }
    if (eq(name, "m_bExportTextures"))         { o->m_bExportTextures = b;         return 1; }
    if (eq(name, "m_bCaptureItemThumbnail"))   { o->m_bCaptureItemThumbnail = b;   return 1; }
    if (eq(name, "m_bShowModalProgressBar"))   { o->m_bShowModalProgressBar = b;   return 1; }
    if (eq(name, "m_bUseAverageColor"))        { o->m_bUseAverageColor = b;        return 1; }
    return 0;
}

// -------------------------------------------------------------- the exports
// Each returns the number of output paths (>=0), -1 if `out` was too small,
// or -2 if the CLO API is not available.

int clo_export_glb(const char* path, void* h, char* out, int outLen) {
    if (!clo_shim_ready()) return -2;
    ImportExportOption local;
    const ImportExportOption& o = h ? *opts(h) : local;
    return writePaths(EXPORT_API->ExportGLB(path ? path : "", o), out, outLen);
}

int clo_export_gltf(const char* path, void* h, int binary, char* out, int outLen) {
    if (!clo_shim_ready()) return -2;
    ImportExportOption local;
    const ImportExportOption& o = h ? *opts(h) : local;
    return writePaths(EXPORT_API->ExportGLTF(path ? path : "", o, binary != 0), out, outLen);
}

int clo_export_fbx(const char* path, void* h, char* out, int outLen) {
    if (!clo_shim_ready()) return -2;
    ImportExportOption local;
    const ImportExportOption& o = h ? *opts(h) : local;
    return writePaths(EXPORT_API->ExportFBX(path ? path : "", o), out, outLen);
}

// ExportOBJ already works from Python WITHOUT options; this variant exists so
// options can finally be honoured.
int clo_export_obj(const char* path, void* h, char* out, int outLen) {
    if (!clo_shim_ready()) return -2;
    ImportExportOption local;
    const ImportExportOption& o = h ? *opts(h) : local;
    return writePaths(EXPORT_API->ExportOBJ(path ? path : "", o), out, outLen);
}

// ExportTechPack returns void: 0 means "no exception", not "file verified".
int clo_export_techpack(const char* path, void* h) {
    if (!clo_shim_ready()) return -2;
    ExportTechpackOption local;
    const ExportTechpackOption& o = h ? *tpOpts(h) : local;
    EXPORT_API->ExportTechPack(path ? path : "", o);
    return 0;
}

}  // extern "C"
