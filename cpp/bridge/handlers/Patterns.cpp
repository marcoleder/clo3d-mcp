#include "CommandDispatcher.h"

namespace clo::bridge {
QJsonArray patternList(SdkAdapter& sdk) {
    QJsonArray list;
    auto count = sdk.GetPatternCount();
    for (int i = 0; i < count; ++i) list.append(QJsonObject{{"index", i}, {"name", json(sdk.GetPatternPieceName(i))}});
    return list;
}
void addPatternHandlers(Registry& r) {
    r["get_pattern_count"] = {Access::Read, [](auto& c, const auto&) { return QJsonObject{{"count", c.sdk.GetPatternCount()}}; }};
    r["get_pattern_list"] = {Access::Read, [](auto& c, const auto&) { auto list = patternList(c.sdk); return QJsonObject{{"patterns", list}, {"count", list.size()}}; }};
    r["get_pattern_info"] = {Access::Read, [](auto& c, const auto& p) {
        int i = index(p, "pattern_index", c.sdk.GetPatternCount());
        return QJsonObject{{"index", i}, {"name", json(c.sdk.GetPatternPieceName(i))}, {"info", parseSdkJson(c.sdk.GetPatternInformation(i))}};
    }};
    r["get_bounding_box"] = {Access::Read, [](auto& c, const auto& p) {
        int i = index(p, "pattern_index", c.sdk.GetPatternCount());
        return QJsonObject{{"index", i}, {"bounding_box", json(c.sdk.GetBoundingBoxOfPattern(i))}};
    }};
    r["get_arrangement_list"] = {Access::Read, [](auto& c, const auto&) { return QJsonObject{{"arrangements", json(c.sdk.GetArrangementList())}}; }};
    r["set_pattern_name"] = {Access::Mutation, [](auto& c, const auto& p) {
        int i = index(p, "pattern_index", c.sdk.GetPatternCount()); auto name = stringValue(p, "name");
        c.change([&] { c.sdk.SetPatternPieceName(i, name.toStdString()); });
        require(c.sdk.GetPatternPieceName(i) == name.toStdString(), "Pattern name readback failed");
        return QJsonObject{{"index", i}, {"name", name}};
    }};
    r["copy_pattern"] = {Access::Mutation, [](auto& c, const auto& p) {
        auto before = c.sdk.GetPatternCount(); int i = index(p, "pattern_index", before);
        float x = numberValue(p.value("x").isUndefined() ? QJsonValue(0) : p["x"], "x");
        float y = numberValue(p.value("y").isUndefined() ? QJsonValue(0) : p["y"], "y");
        auto n = c.change([&] { return c.sdk.CopyPatternPieceMove(i, x, y); });
        auto after = c.sdk.GetPatternCount();
        require(n >= 0 && n < after && after > before, "CopyPatternPieceMove postcondition failed");
        return QJsonObject{{"copied", true}, {"source_index", i}, {"new_index", n}, {"offset", QJsonArray{x, y}}};
    }};
    r["delete_pattern"] = {Access::Mutation, [](auto& c, const auto& p) {
        auto before = c.sdk.GetPatternCount(); int i = index(p, "pattern_index", before);
        c.change([&] { c.sdk.DeletePatternPiece(i); });
        require(c.sdk.GetPatternCount() == before - 1, "DeletePatternPiece postcondition failed");
        return QJsonObject{{"deleted", true}, {"index", i}};
    }};
    r["flip_pattern"] = {Access::Mutation, [](auto& c, const auto& p) {
        int i = index(p, "pattern_index", c.sdk.GetPatternCount());
        bool horizontal = boolValue(p, "horizontal", true), each = boolValue(p, "each", true);
        c.change([&] { c.sdk.FlipPatternPiece(i, horizontal, each); });
        return QJsonObject{{"flipped", true}, {"index", i}, {"horizontal", horizontal}, {"each", each}};
    }};
    r["create_pattern"] = {Access::Mutation, [](auto& c, const auto& p) {
        if (!p["points"].isArray() || p["points"].toArray().size() < 3) throw ValidationError("points requires at least three vertices");
        SdkAdapter::Points points;
        for (const auto& v : p["points"].toArray()) {
            if (!v.isArray() || v.toArray().size() < 2 || v.toArray().size() > 3) throw ValidationError("A point must be [x,y] or [x,y,type]");
            auto a = v.toArray(); int type = a.size() == 3 ? static_cast<int>(integerValue(a[2], 0, 3, "point type")) : 0;
            if (type == 1) throw ValidationError("Point type must be 0, 2 or 3");
            points.emplace_back(numberValue(a[0], "point x"), numberValue(a[1], "point y"), type);
        }
        auto before = c.sdk.GetPatternCount();
        auto result = c.change([&] { return c.sdk.CreatePatternWithPoints(points); });
        require(result >= 0 && c.sdk.GetPatternCount() > before, "CreatePatternWithPoints postcondition failed");
        return QJsonObject{{"created", true}, {"point_count", static_cast<qint64>(points.size())}, {"result", result}};
    }};
}
}
