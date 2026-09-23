#include "TestSupport.h"
#include "CommandDispatcher.h"
#include "ExportOptions.h"
#include "Artifacts.h"
#include <QCoreApplication>
#include <QFile>
#include <QTemporaryDir>
#include <QJsonDocument>
#include <QtEndian>

using namespace clo::bridge;
void write(const QString& path, QByteArray bytes) { QFile file(path); CHECK(file.open(QIODevice::WriteOnly)); CHECK(file.write(bytes) == bytes.size()); }
int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    try {
        QTemporaryDir directory; JsonFiles files; SceneReviewState review(directory.path(), files);
        SdkAdapter sdk; int mutations = 0, refreshes = 0, snapshots = 0, fabrics = 2, avatars = 1;
        SdkAdapter::Strings names{"bodice", "sleeve"};
        std::string project = directory.filePath("original.zprj").toStdString();
        write(QString::fromStdString(project), "fixture");
        sdk.available = [] { return true; };
        sdk.GetPatternCount = [&] { return names.size(); };
        sdk.GetPatternPieceName = [&](int i) { return names.at(i); };
        sdk.GetPatternInformation = [](int) { return "{}"; };
        sdk.GetProjectFilePath = [&] { return project; };
        sdk.GetFabricCount = [&](int selector) { CHECK(selector == -2); return fabrics; };
        sdk.GetAvatarCount = [&] { return avatars; };
        sdk.GetAvatarNameList = [] { return SdkAdapter::Strings{"avatar"}; };
        sdk.GetColorwayCount = [] { return 1u; };
        sdk.Refresh3DWindow = [&] { ++refreshes; };
        sdk.ExportSnapshot3D = [&](const std::string&) -> std::vector<SdkAdapter::Strings> { ++snapshots; throw std::runtime_error("capture failed"); };
        sdk.SetPatternPieceName = [&](int i, const std::string& name) { ++mutations; names.at(i) = name; };
        sdk.AddFabric = [&](const std::string&) { ++mutations; ++fabrics; return fabrics - 1; };
        sdk.ImportAvatar = [&](const std::string&, const auto& options) { CHECK(options.bAdd && !options.bMoveGarment); ++mutations; ++avatars; names.pop_back(); return true; };
        sdk.ImportFile = [&](const std::string& p) { ++mutations; project = p; return true; };
        CommandDispatcher dispatcher(sdk, review, directory.path());
        CHECK(dispatcher.registry().size() == 48);
        if (argc == 2 && QString::fromLocal8Bit(argv[1]) == "--registry") {
            std::cout << QJsonDocument(QJsonArray::fromStringList(dispatcher.registry().keys())).toJson().toStdString();
            return 0;
        }
        if (argc == 2) {
            QFile fixture(QString::fromLocal8Bit(argv[1])); CHECK(fixture.open(QIODevice::ReadOnly));
            auto contracts = QJsonDocument::fromJson(fixture.readAll()).object();
            CHECK(!contracts.isEmpty());
            for (const auto& example : contracts["export_paths"].toArray()) {
                auto row = example.toObject();
                if (row["error"].toBool()) throws([&] { exportPaths(row["input"]); });
                else CHECK(exportPaths(row["input"]) == row["output"].toArray());
            }
        }
        auto call = [&](const QString& type, QJsonObject params = {}) {
            return dispatcher.dispatch({{"id", "test"}, {"type", type}, {"params", params}});
        };
        CHECK(call("ping")["result"].toObject()["backend"] == "cpp");
        CHECK(!call("ping")["result"].toObject().contains("exported"));
        CHECK(call("debug_api")["status"] == "error");
        CHECK(call("set_live_preview", {{"enabled", true}})["result"].toObject()["snapshot_path"].isNull());
        CHECK(call("set_pattern_name", {{"pattern_index", 0}, {"name", "袖"}})["status"] == "success");
        CHECK(refreshes == 1 && snapshots == 0);
        CHECK(call("get_pattern_count")["status"] == "success"); CHECK(refreshes == 1);
        CHECK(call("refresh_view")["result"].toObject()["repainted"] == false); CHECK(snapshots == 0);
        for (const auto& bad : {QJsonValue(true), QJsonValue(-1), QJsonValue(1.5), QJsonValue(1e30), QJsonValue("0")}) {
            auto result = call("set_pattern_name", {{"pattern_index", bad}, {"name", "bad"}});
            CHECK(result["status"] == "error" && !result.contains("outcome"));
        }
        CHECK(mutations == 1);
        CHECK(call("get_pattern_info", {{"pattern_index", 0}})["result"].toObject()["info"].toObject().isEmpty());
        CHECK(parseSdkJson("bad").toObject()["raw"] == "bad");
        CHECK(exportPaths(QJsonArray{QJsonArray{}, QJsonArray{"a", QJsonArray{"b"}}}).size() == 2);
        throws([] { exportPaths(QJsonArray{"a", 4}); });
        auto opts = modelOptions({}); CHECK(opts.bExportGarment && opts.bExportAvatar && opts.scale == 1 && opts.axisY == 1);
        CHECK(!modelOptions({{"options", QJsonObject{{"bExportAvatar", false}}}}).bExportAvatar);
        for (const auto& invalid : {QJsonObject{{"bExportAvatar", 0}}, QJsonObject{{"weldType", 4}}, QJsonObject{{"axisY", -1}}, QJsonObject{{"scale", 1e100}}, QJsonObject{{"unknown", true}}})
            throws([&] { modelOptions({{"options", invalid}}); });
        CHECK(techpackOptions({}).m_bSaveZprj);
        throws([] { techpackOptions({{"options", QJsonObject{{"m_bSaveZprj", "false"}}}}); });
        // A CLO-style prefix before a ZIP payload is legal; stale files are not.
        auto archive = directory.filePath("saved.zprj"); Artifacts artifacts(archive);
        QByteArray end(22, '\0'); end.replace(0, 4, QByteArray("PK\005\006", 4));
        qToLittleEndian<quint16>(1, end.data() + 10); qToLittleEndian<quint32>(4, end.data() + 12);
        write(archive, QByteArray(" ZPRJ CLO prefixPK\001\002", 20) + end);
        artifacts.verify({archive});
        Artifacts unchanged(archive); throws([&] { unchanged.verify({archive}); });
        unchanged.verify({archive}, {}, false); // An existing referenced resource may be reused.
        auto capture = directory.filePath("preview.png");
        CHECK(call("set_live_preview", {{"path", capture}})["status"] == "success");
        auto changed = call("set_pattern_name", {{"pattern_index", 0}, {"name", "new"}});
        CHECK(changed["status"] == "success" && changed["result"].toObject().contains("preview_error"));
        CHECK(!review.required()); CHECK(snapshots == 1);
        call("set_live_preview", {{"enabled", false}}); // Resets compatibility mode.
        CHECK(call("refresh_view")["result"].toObject()["preview_mode"] == "native"); CHECK(snapshots == 1);
        auto avatar = directory.filePath("avatar.avt"); write(avatar, "fixture");
        auto unknown = call("import_avatar", {{"file_path", avatar}});
        CHECK(unknown["outcome"] == "unknown" && unknown["review_persisted"] == true);
        auto before = mutations;
        CHECK(call("import_avatar", {{"file_path", avatar}})["outcome"] == "unknown"); CHECK(mutations == before);
        CHECK(call("get_pattern_list")["status"] == "success");
        CHECK(call("export_snapshot", {{"file_path", capture}})["outcome"] == "unknown");
        CHECK(call("open_file", {{"file_path", QString::fromStdString(project)}})["outcome"] == "unknown"); CHECK(mutations == before);
        auto backup = directory.filePath("backup 袖.zprj"); write(backup, "fixture");
        CHECK(call("open_file", {{"file_path", backup}})["status"] == "success"); CHECK(!review.required());
        before = mutations;
        CHECK(call("open_file", {{"file_path", backup}})["result"].toObject()["already_active"] == true); CHECK(mutations == before);
        auto link = directory.filePath("alias.zprj"); CHECK(QFile::link(backup, link)); CHECK(samePath(backup, link));
        CHECK(call("open_file", {{"file_path", link}})["result"].toObject()["already_active"] == true); CHECK(mutations == before);
        // Cancelled project import and failed marker writes remain fail-closed.
        sdk.ImportFile = [&](const std::string&) { ++mutations; return true; };
        CommandDispatcher cancelled(sdk, review, directory.path());
        files.beforeWrite = [](const auto&, const auto&) { throw std::runtime_error("disk full"); };
        auto response = cancelled.dispatch({{"id", "cancel"}, {"type", "open_file"}, {"params", QJsonObject{{"file_path", directory.filePath("original.zprj")}}}});
        CHECK(response["outcome"] == "unknown" && response["review_persisted"] == false && review.required());
        CHECK(call("stop_bridge")["status"] == "success");
        files.beforeWrite = {}; review.clear();
        sdk.NewProject = [&] { ++mutations; names.clear(); avatars = 0; fabrics = 1; project = "NULL"; };
        CommandDispatcher reset(sdk, review, directory.path());
        CHECK(reset.dispatch({{"id", "reset"}, {"type", "new_project"}, {"params", QJsonObject{}}})["status"] == "success");
        std::cout << "Native contracts, strict inputs, preview, uncertain imports and recovery passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
