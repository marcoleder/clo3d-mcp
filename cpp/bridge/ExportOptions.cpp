#include "ExportOptions.h"
#include "ResultContracts.h"

namespace clo::bridge {
namespace {
QJsonObject options(const QJsonObject& params) {
    if (!params.contains("options") || params["options"].isNull()) return {};
    if (!params["options"].isObject()) throw ValidationError("options must be an object");
    return params["options"].toObject();
}
}
Marvelous::ImportExportOption modelOptions(const QJsonObject& params) {
    Marvelous::ImportExportOption result; // SDK constructor defaults, never zero initialization.
    const auto values = options(params);
    for (auto it = values.begin(); it != values.end(); ++it) {
        auto key = it.key();
#define BOOL_OPTION(name) if (key == #name) { result.name = boolValue(values, #name, false); continue; }
        BOOL_OPTION(bExportGarment) BOOL_OPTION(bExportAvatar) BOOL_OPTION(bSingleObject)
        BOOL_OPTION(bThin) BOOL_OPTION(bIncludeHiddenObject) BOOL_OPTION(bIncludeInnerShape)
        BOOL_OPTION(bSaveColorWays) BOOL_OPTION(bSaveInZip)
        BOOL_OPTION(bInvertX) BOOL_OPTION(bInvertY) BOOL_OPTION(bInvertZ)
#undef BOOL_OPTION
        if (key == "weldType") { result.weldType = static_cast<Marvelous::WELD_TYPE>(integer(values, "weldType", 0, 3)); continue; }
#define AXIS_OPTION(name) if (key == #name) { result.name = static_cast<int>(integer(values, #name, 0, 2)); continue; }
        AXIS_OPTION(axisX) AXIS_OPTION(axisY) AXIS_OPTION(axisZ)
#undef AXIS_OPTION
        if (key == "scale") { result.scale = numberValue(it.value(), "scale"); continue; }
        throw ValidationError(("Unsupported model option: " + key).toStdString());
    }
    return result;
}
Marvelous::ExportTechpackOption techpackOptions(const QJsonObject& params) {
    Marvelous::ExportTechpackOption result;
    auto values = options(params);
    for (auto it = values.begin(); it != values.end(); ++it) {
        auto key = it.key();
#define BOOL_OPTION(name) if (key == #name) { result.name = boolValue(values, #name, false); continue; }
        BOOL_OPTION(m_bSaveZprj) BOOL_OPTION(m_bSaveZpac) BOOL_OPTION(m_bExportTextures)
        BOOL_OPTION(m_bCaptureItemThumbnail) BOOL_OPTION(m_bShowModalProgressBar) BOOL_OPTION(m_bUseAverageColor)
#undef BOOL_OPTION
        throw ValidationError(("Unsupported tech pack option: " + key).toStdString());
    }
    return result;
}
}
