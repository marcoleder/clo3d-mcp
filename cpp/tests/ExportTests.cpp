#include "TestSupport.h"
#include "CommandDispatcher.h"
#include <QCoreApplication>
#include <QFile>
#include <QImage>
#include <QJsonDocument>
#include <QTemporaryDir>

using namespace clo::bridge;
void write(const QString& path, const QByteArray& bytes) { QFile f(path); CHECK(f.open(QIODevice::WriteOnly)); CHECK(f.write(bytes) == bytes.size()); }
int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    try {
        QTemporaryDir directory; JsonFiles files; SceneReviewState review(directory.path(), files);
        SdkAdapter sdk; int calls = 0; bool avatarOption = true;
        sdk.available = [] { return true; };
        sdk.ExportOBJ = [&](const std::string& path, const auto& options) {
            ++calls; avatarOption = options.bExportAvatar;
            write(QString::fromStdString(path), "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
            return SdkAdapter::Strings{path};
        };
        sdk.ExportGLTF = [&](const std::string& path, const auto&, bool binary) {
            CHECK(!binary); ++calls;
            write(QString::fromStdString(path), R"({"asset":{"version":"2.0"},"meshes":[{}],"buffers":[{"uri":"missing.bin"}]})");
            return SdkAdapter::Strings{path};
        };
        sdk.ExportSnapshot3D = [&](const std::string& path) {
            ++calls; QImage img(12, 16, QImage::Format_ARGB32); img.fill(Qt::red); CHECK(img.save(QString::fromStdString(path)));
            return std::vector<SdkAdapter::Strings>{{}, {path}};
        };
        sdk.GetCurrentColorwayIndex = [] { return 2u; };
        sdk.ExportTurntableImagesByColorwayIndex = [&](const std::string& path, unsigned n, unsigned colorway, unsigned width, unsigned height) {
            CHECK(colorway == 2); ++calls; SdkAdapter::Strings result;
            for (unsigned i = 0; i < n; ++i) {
                auto imagePath = QString::fromStdString(path) + QString::number(i) + ".png";
                QImage image(width, height, QImage::Format_ARGB32); image.fill(Qt::red); CHECK(image.save(imagePath)); result.push_back(imagePath.toStdString());
            }
            return result;
        };
        sdk.ExportTechPack = [&](const std::string& path, const Marvelous::ExportTechpackOption& options) {
            CHECK(!options.m_bSaveZprj && !options.m_bSaveZpac && !options.m_bShowModalProgressBar); ++calls;
            write(QString::fromStdString(path), R"({"thumbnail":["missing.png"]})");
        };
        CommandDispatcher dispatcher(sdk, review, directory.path());
        auto call = [&](const QString& type, const QJsonObject& p) { return dispatcher.dispatch({{"id", "export-test"}, {"type", type}, {"params", p}}); };
        auto obj = directory.filePath("mesh 袖.obj");
        CHECK(call("export_obj", {{"file_path", obj}, {"options", QJsonObject{{"bad", 1}}}})["status"] == "error"); CHECK(calls == 0);
        auto result = call("export_obj", {{"file_path", obj}, {"options", QJsonObject{{"bExportAvatar", false}}}});
        CHECK(result["status"] == "success" && !avatarOption && calls == 1);
        CHECK(result["result"].toObject()["via"] == "cpp_plugin");
        auto snapshot = call("export_snapshot", {{"file_path", directory.filePath("snapshot.png")}});
        CHECK(snapshot["status"] == "success");
        CHECK(snapshot["result"].toObject()["file_path"].toArray().size() == 2);
        CHECK(snapshot["result"].toObject()["file_paths"].toArray().size() == 1);
        CHECK(call("export_turntable", {{"file_path", directory.filePath("turn.png")}, {"number_of_images", 2}, {"width", 16}, {"height", 12}})["status"] == "success");
        CHECK(call("export_gltf", {{"file_path", directory.filePath("mesh.gltf")}})["outcome"] == "unknown"); CHECK(review.required()); review.clear();
        CHECK(call("export_tech_pack", {{"file_path", directory.filePath("tech.json")}, {"options", QJsonObject{{"m_bSaveZprj", false}, {"m_bSaveZpac", false}, {"m_bShowModalProgressBar", false}}}})["outcome"] == "unknown");
        CHECK(review.required());
        std::cout << "Native typed exports, geometry, images, resources and tech pack sidecars passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
