#include "CommandDispatcher.h"

namespace clo::bridge {
void addColorwayHandlers(Registry& r) {
    r["get_colorways"] = {Access::Read, [](auto& c, const auto&) {
        auto count = c.sdk.GetColorwayCount(), current = c.sdk.GetCurrentColorwayIndex();
        auto names = c.sdk.GetColorwayNameList(); QJsonArray list;
        for (unsigned i = 0; i < (names.empty() ? count : names.size()); ++i) {
            QJsonObject item{{"index", json(i)}, {"current", i == current}};
            if (i < names.size()) item["name"] = json(names[i]);
            list.append(item);
        }
        return QJsonObject{{"colorways", list}, {"count", json(count)}, {"current_index", json(current)}};
    }};
    r["set_current_colorway"] = {Access::Mutation, [](auto& c, const auto& p) {
        int i = index(p, "colorway_index", c.sdk.GetColorwayCount());
        c.change([&] { c.sdk.SetCurrentColorwayIndex(i); });
        require(c.sdk.GetCurrentColorwayIndex() == static_cast<unsigned>(i), "Current colorway readback failed");
        return QJsonObject{{"set", true}, {"colorway_index", i}};
    }};
    r["set_colorway_name"] = {Access::Mutation, [](auto& c, const auto& p) {
        int i = index(p, "colorway_index", c.sdk.GetColorwayCount()); auto name = stringValue(p, "name");
        c.change([&] { c.sdk.SetColorwayName(i, name.toStdString()); });
        require(c.sdk.GetColorwayName(i) == name.toStdString(), "Colorway name readback failed");
        return QJsonObject{{"set", true}, {"colorway_index", i}, {"name", name}};
    }};
    r["copy_colorway"] = {Access::Mutation, [](auto& c, const auto& p) {
        auto before = c.sdk.GetColorwayCount(); int i = index(p, "colorway_index", before);
        int option = integer(p, "copy_option", 0, 2, 0);
        auto result = c.change([&] { return c.sdk.CopyColorway(i, option); });
        auto after = c.sdk.GetColorwayCount();
        require(after > before && result < after, "CopyColorway postcondition failed");
        return QJsonObject{{"copied", true}, {"source_index", i}, {"copy_option", option}, {"new_index", json(result)}};
    }};
    r["delete_colorway"] = {Access::Mutation, [](auto& c, const auto& p) {
        auto before = c.sdk.GetColorwayCount(); int i = index(p, "colorway_index", before);
        if (before <= 1) throw ValidationError("Cannot delete the last colorway");
        c.change([&] { c.sdk.DeleteColorwayItem(i); });
        require(c.sdk.GetColorwayCount() == before - 1, "DeleteColorwayItem postcondition failed");
        return QJsonObject{{"deleted", true}, {"colorway_index", i}};
    }};
}
}
