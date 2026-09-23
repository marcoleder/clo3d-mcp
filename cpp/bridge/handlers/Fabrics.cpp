#include "CommandDispatcher.h"

namespace clo::bridge {
QJsonObject addFabric(CommandContext& c, const QJsonObject& p) {
    auto path = inputPath(p); auto before = c.sdk.GetFabricCount(-2);
    auto i = c.change([&] { return c.sdk.AddFabric(path.toStdString()); });
    auto after = c.sdk.GetFabricCount(-2);
    require(i < after && after > before, "AddFabric did not return a valid new fabric");
    return {{"fabric_index", json(i)}, {"file_path", path}};
}
void addFabricHandlers(Registry& r) {
    r["get_fabric_count"] = {Access::Read, [](auto& c, const auto&) { return QJsonObject{{"count", json(c.sdk.GetFabricCount(-2))}}; }};
    r["get_fabric_list"] = {Access::Read, [](auto& c, const auto&) {
        auto count = c.sdk.GetFabricCount(-2); QJsonArray list;
        for (unsigned i = 0; i < count; ++i) list.append(QJsonObject{{"index", json(i)}, {"name", json(c.sdk.GetFabricName(i))}});
        return QJsonObject{{"fabrics", list}, {"count", json(count)}};
    }};
    r["add_fabric"] = {Access::Mutation, [](auto& c, const auto& p) { auto result = addFabric(c, p); result["added"] = true; return result; }};
    r["import_fabric"] = {Access::Mutation, [](auto& c, const auto& p) { auto result = addFabric(c, p); result["imported"] = true; return result; }};
    r["replace_fabric"] = {Access::Mutation, [](auto& c, const auto& p) {
        int i = index(p, "fabric_index", c.sdk.GetFabricCount(-2)); auto path = inputPath(p);
        require(c.change([&] { return c.sdk.ReplaceFabric(i, path.toStdString()); }), "ReplaceFabric returned false");
        return QJsonObject{{"replaced", true}, {"fabric_index", i}, {"file_path", path}};
    }};
    r["delete_fabric"] = {Access::Mutation, [](auto& c, const auto& p) {
        auto before = c.sdk.GetFabricCount(-2); int i = index(p, "fabric_index", before);
        require(c.change([&] { return c.sdk.DeleteFabric(i); }), "DeleteFabric returned false");
        require(c.sdk.GetFabricCount(-2) == before - 1, "DeleteFabric postcondition failed");
        return QJsonObject{{"deleted", true}, {"fabric_index", i}};
    }};
    r["assign_fabric"] = {Access::Mutation, [](auto& c, const auto& p) {
        int f = index(p, "fabric_index", c.sdk.GetFabricCount(-2)), i = index(p, "pattern_index", c.sdk.GetPatternCount());
        int option = static_cast<int>(integer(p, "assign_option", 1, 3, 1));
        require(c.change([&] { return c.sdk.AssignFabricToPattern(f, i, option); }), "AssignFabricToPattern returned false");
        require(c.sdk.GetFabricIndexForPattern(i) == f, "Fabric assignment readback failed");
        return QJsonObject{{"assigned", true}, {"fabric_index", f}, {"pattern_index", i}};
    }};
    r["get_fabric_for_pattern"] = {Access::Read, [](auto& c, const auto& p) {
        int i = index(p, "pattern_index", c.sdk.GetPatternCount());
        return QJsonObject{{"pattern_index", i}, {"fabric_index", c.sdk.GetFabricIndexForPattern(i)}};
    }};
    r["set_fabric_color"] = {Access::Mutation, [](auto& c, const auto& p) {
        int i = index(p, "fabric_index", c.sdk.GetFabricCount(-2));
        auto face = integer(p, "material_face", 0, 2, 0);
        int red = integer(p, "r", 0, 255, 255), green = integer(p, "g", 0, 255, 255);
        int blue = integer(p, "b", 0, 255, 255), alpha = integer(p, "a", 0, 255, 255);
        require(c.change([&] { return c.sdk.SetFabricPBRMaterialBaseColor(i, face, red/255.f, green/255.f, blue/255.f, alpha/255.f); }),
                "SetFabricPBRMaterialBaseColor returned false");
        return QJsonObject{{"set", true}, {"fabric_index", i}, {"color", QJsonArray{red, green, blue, alpha}}};
    }};
}
}
