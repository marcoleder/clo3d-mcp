#include "CommandDispatcher.h"
#include <QFileInfo>

namespace clo::bridge {
QJsonObject importAvatar(CommandContext& c, const QJsonObject& p) {
    auto path = inputPath(p); auto extension = QFileInfo(path).suffix().toLower();
    auto apf = stringValue(p, "apf_path", "");
    if (extension != "avt" && extension != "avac") throw ValidationError("Avatar file must be .avt or .avac");
    if (extension == "avt" && !apf.isEmpty()) throw ValidationError("apf_path is supported only for .avac");
    if (!apf.isEmpty()) inputPath(p, "apf_path");
    auto before = c.sdk.GetAvatarCount(); auto patterns = patternList(c.sdk); auto project = c.sdk.GetProjectFilePath();
    bool result = c.change([&] {
        if (extension == "avac") return c.sdk.ImportAVAC(path.toStdString(), apf.toStdString());
        Marvelous::ImportExportOption options; options.bAdd = true; options.bMoveGarment = false;
        return c.sdk.ImportAvatar(path.toStdString(), options);
    });
    require(result && c.sdk.GetAvatarCount() > before, "Avatar import did not add an avatar");
    require(patternList(c.sdk) == patterns && c.sdk.GetProjectFilePath() == project, "Avatar import unexpectedly changed the garment or project");
    return {{"imported", true}, {"file_path", path}};
}
void addAvatarHandlers(Registry& r) {
    r["get_avatars"] = {Access::Read, [](auto& c, const auto&) {
        auto count = c.sdk.GetAvatarCount(); auto names = c.sdk.GetAvatarNameList(); auto genders = c.sdk.GetAvatarGenderList();
        QJsonArray list;
        for (size_t i = 0; i < names.size(); ++i) {
            QJsonObject item{{"index", static_cast<qint64>(i)}, {"name", json(names[i])}};
            if (i < genders.size()) item["gender"] = genders[i];
            list.append(item);
        }
        return QJsonObject{{"avatars", list}, {"count", count}};
    }};
    r["get_avatar_genders"] = {Access::Read, [](auto& c, const auto&) { return QJsonObject{{"genders", json(c.sdk.GetAvatarGenderList())}}; }};
    r["show_hide_avatar"] = {Access::Mutation, [](auto& c, const auto& p) {
        bool show = boolValue(p, "show", true); auto count = c.sdk.GetAvatarCount();
        c.change([&] { c.sdk.SetShowHideAvatar(show); });
        for (int i = 0; i < count; ++i) require(c.sdk.IsShowAvatar(i) == show, "Avatar visibility readback failed");
        return QJsonObject{{"visible", show}};
    }};
    r["import_avatar"] = {Access::Mutation, importAvatar};
}
}
