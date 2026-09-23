#include "CommandDispatcher.h"
#include "Artifacts.h"
#include "ExportOptions.h"
#include <QDir>
#include <QFileInfo>
#include <QSet>

namespace clo::bridge {
void addExportHandlers(Registry& r) {
    for (const auto& format : {QString("obj"), QString("fbx"), QString("glb"), QString("gltf")}) {
        r["export_" + format] = {Access::ArtifactWrite, [format](auto& c, const auto& p) {
            auto path = outputPath(p); auto options = modelOptions(p); Artifacts artifacts(path);
            auto values = c.change([&] {
                if (format == "obj") return c.sdk.ExportOBJ(path.toStdString(), options);
                if (format == "fbx") return c.sdk.ExportFBX(path.toStdString(), options);
                if (format == "glb") return c.sdk.ExportGLB(path.toStdString(), options);
                return c.sdk.ExportGLTF(path.toStdString(), options, false);
            });
            auto paths = exportPaths(json(values)); artifacts.verify(paths);
            QJsonObject result{{"exported", true}, {"file_paths", paths}, {"format", format}, {"via", "cpp_plugin"}};
            if (format != "obj") result["file_path"] = json(values);
            return result;
        }};
    }
    r["export_thumbnail"] = {Access::ArtifactWrite, [](auto& c, const auto& p) {
        auto path = outputPath(p); Artifacts artifacts(path);
        auto value = c.change([&] { return c.sdk.ExportThumbnail3D(path.toStdString()); });
        artifacts.verify(exportPaths(json(value)));
        return QJsonObject{{"exported", true}, {"file_path", json(value)}};
    }};
    r["export_snapshot"] = {Access::ArtifactWrite, [](auto& c, const auto& p) {
        auto path = outputPath(p); Artifacts artifacts(path);
        auto value = c.change([&] { return c.sdk.ExportSnapshot3D(path.toStdString()); });
        auto paths = exportPaths(json(value)); artifacts.verify(paths);
        return QJsonObject{{"exported", true}, {"file_path", json(value)}, {"file_paths", paths}};
    }};
    r["export_turntable"] = {Access::ArtifactWrite, [](auto& c, const auto& p) {
        auto path = outputPath(p); auto ext = QFileInfo(path).suffix().toLower();
        if (ext != "png" && ext != "jpg" && ext != "jpeg") throw ValidationError("Turntable output must be an image filename");
        int count = integer(p, "number_of_images", 1, INT_MAX, 36);
        int width = integer(p, "width", 1, INT_MAX, 2500), height = integer(p, "height", 1, INT_MAX, 2500);
        auto colorway = c.sdk.GetCurrentColorwayIndex(); Artifacts artifacts(path);
        auto values = c.change([&] { return c.sdk.ExportTurntableImagesByColorwayIndex(path.toStdString(), count, colorway, width, height); });
        auto paths = exportPaths(json(values));
        require(paths.size() == count, "CLO did not produce all requested turntable images");
        artifacts.verify(paths, QSize(width, height));
        return QJsonObject{{"exported", true}, {"file_paths", paths}, {"number_of_images", count}, {"width", width}, {"height", height}};
    }};
    r["export_tech_pack"] = {Access::ProjectWrite, [](auto& c, const auto& p) {
        auto path = outputPath(p);
        if (QFileInfo(path).suffix().toLower() != "json") throw ValidationError("Tech pack output must be a .json filename");
        auto options = techpackOptions(p); Artifacts artifacts(path);
        c.change([&] { c.sdk.ExportTechPack(path.toStdString(), options); });
        artifacts.verify({path});
        auto root = Artifacts::readObject(path);
        require(!root.isEmpty(), "CLO produced an empty tech pack");
        QSet<QString> sidecars;
        auto addSidecar = [&](const QJsonValue& value) {
            require(value.isString() && !value.toString().isEmpty(), "Missing tech pack sidecar path");
            auto file = value.toString();
            sidecars.insert(QFileInfo(file).isAbsolute() ? file : QFileInfo(path).dir().filePath(file));
        };
        if (options.m_bSaveZprj) addSidecar(root.value("zprjPath"));
        if (options.m_bSaveZpac) addSidecar(root.value("zpacPath"));
        QJsonArray projectPaths;
        for (const auto& file : sidecars) projectPaths.append(file);
        if (!projectPaths.isEmpty()) artifacts.verify(projectPaths);
        sidecars.clear();
        std::function<void(const QJsonValue&, bool)> collect = [&](const QJsonValue& v, bool artifact) {
            if (v.isObject()) {
                const auto object = v.toObject();
                for (auto it = object.begin(); it != object.end(); ++it)
                    collect(it.value(), artifact || it.key().contains("thumbnail", Qt::CaseInsensitive)
                            || (options.m_bExportTextures && it.key() == "textureList"));
            } else if (v.isArray()) {
                for (const auto& item : v.toArray()) collect(item, artifact);
            } else if (artifact && v.isString() && !v.toString().isEmpty()) {
                auto ext = QFileInfo(v.toString()).suffix().toLower();
                if (ext == "png" || ext == "jpg" || ext == "jpeg" || ext == "tif" || ext == "tiff") addSidecar(v);
            }
        };
        collect(root, false);
        QJsonArray paths;
        for (const auto& file : sidecars) paths.append(file);
        // CLO reuses already exported texture/thumbnail resources, retaining
        // their timestamps. The tech-pack JSON and requested project saves
        // must be fresh; referenced resources must be present and valid.
        if (!paths.isEmpty()) artifacts.verify(paths, {}, false);
        return QJsonObject{{"exported", true}, {"file_path", path}, {"via", "cpp_plugin"}};
    }};
}
}
