#include "CommandDispatcher.h"
#include "Artifacts.h"
#include <QFileInfo>

namespace clo::bridge {
namespace {
QJsonObject signature(SdkAdapter& sdk) {
    return {{"project_path", json(sdk.GetProjectFilePath())}, {"patterns", patternList(sdk)},
        {"avatars", sdk.GetAvatarCount()}, {"avatar_names", json(sdk.GetAvatarNameList())},
        {"fabrics", json(sdk.GetFabricCount(-2))}, {"colorways", json(sdk.GetColorwayCount())}};
}
QJsonObject checkedImport(CommandContext& c, const QJsonObject& p) {
    auto path = inputPath(p); auto extension = QFileInfo(path).suffix().toLower();
    if (extension == "avt" || extension == "avac") return importAvatar(c, {{"file_path", path}});
    if (extension == "zfab" || extension == "jfab") { auto result = addFabric(c, p); result["imported"] = true; return result; }
    auto before = QString::fromStdString(c.sdk.GetProjectFilePath());
    if (extension == "zprj" && samePath(before, path)) {
        if (c.review.required()) throw OutcomeUnknown("Restore a distinct .zprj backup; active-path reload cannot be verified");
        return {{"verified", true}, {"already_active", true}};
    }
    auto scene = extension == "zprj" ? QJsonObject{} : signature(c.sdk);
    auto camera = extension == "zcmr" ? c.sdk.GetCustomViewInformation() : std::string{};
    require(c.change([&] { return c.sdk.ImportFile(path.toStdString()); }), "ImportFile returned false");
    if (extension == "zprj") {
        require(samePath(QString::fromStdString(c.sdk.GetProjectFilePath()), path), "Requested project is not active after ImportFile");
        c.review.clear();
    } else {
        require(signature(c.sdk) != scene || (extension == "zcmr" && c.sdk.GetCustomViewInformation() != camera),
                "ImportFile returned true without an observable scene change");
    }
    return {{"verified", true}, {"already_active", false}};
}
}
void addSceneHandlers(Registry& r) {
    r["get_project_info"] = {Access::Read, [](auto& c, const auto&) {
        return QJsonObject{{"project_name", json(c.sdk.GetProjectName())}, {"project_path", json(c.sdk.GetProjectFilePath())},
            {"clo_version", QString("%1.%2.%3").arg(c.sdk.GetMajorVersion()).arg(c.sdk.GetMinorVersion()).arg(c.sdk.GetPatchVersion())},
            {"pattern_count", c.sdk.GetPatternCount()}, {"fabric_count", json(c.sdk.GetFabricCount(-2))}, {"colorway_count", json(c.sdk.GetColorwayCount())}};
    }};
    r["get_garment_info"] = {Access::Read, [](auto& c, const auto&) {
        return QJsonObject{{"garment_info", parseSdkJson(c.sdk.ExportGarmentInformationToStream(), QJsonValue::Null)}};
    }};
    r["new_project"] = {Access::Mutation, [](auto& c, const auto&) {
        c.change([&] { c.sdk.NewProject(); });
        // CLO 2026.1 reports "NULL" after reset and its built-in Untitled.zprj
        // template at startup. A saved empty document is neither of these.
        auto path = QString::fromStdString(c.sdk.GetProjectFilePath()).replace('\\', '/');
        bool untitled = path.isEmpty() || path == "NULL" || path.endsWith("/Preset/Project/CLO/Untitled.zprj", Qt::CaseInsensitive);
        require(c.sdk.GetPatternCount() == 0 && c.sdk.GetAvatarCount() == 0 && c.sdk.GetColorwayCount() == 1
                && c.sdk.GetFabricCount(-2) == 1 && untitled, "NewProject reset could not be verified");
        return QJsonObject{{"created", true}};
    }};
    r["open_file"] = {Access::Recovery, [](auto& c, const auto& p) {
        auto result = checkedImport(c, p); result["opened"] = true; result["file_path"] = p["file_path"]; return result;
    }};
    r["import_file"] = {Access::Recovery, [](auto& c, const auto& p) {
        auto result = checkedImport(c, p); result["imported"] = true; result["file_path"] = p["file_path"]; return result;
    }};
    r["save_file"] = {Access::ProjectWrite, [](auto& c, const auto& p) {
        auto path = outputPath(p); Artifacts artifacts(path);
        auto actual = c.change([&] { return c.sdk.ExportZPrj(path.toStdString()); });
        auto paths = exportPaths(json(actual)); artifacts.verify(paths);
        return QJsonObject{{"saved", true}, {"file_path", json(actual)}};
    }};
}
}
