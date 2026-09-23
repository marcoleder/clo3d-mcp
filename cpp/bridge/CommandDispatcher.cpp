#include "CommandDispatcher.h"
#include "Artifacts.h"
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonDocument>
#include <QThread>
#include <QCoreApplication>

namespace clo::bridge {
CommandDispatcher::CommandDispatcher(SdkAdapter sdk, SceneReviewState& review, QString directory)
    : sdk_(std::move(sdk)), review_(review), directory_(std::move(directory)) {
    addSceneHandlers(registry_); addPatternHandlers(registry_); addFabricHandlers(registry_);
    addColorwayHandlers(registry_); addAvatarHandlers(registry_); addSimulationHandlers(registry_); addExportHandlers(registry_);
    registry_["ping"] = {Access::Read, [this](auto&, const auto&) {
        return QJsonObject{{"pong", true}, {"in_clo3d", true}, {"backend", "cpp"}, {"build", "1"},
            {"sdk_version", "2026.1.224"}, {"qt_version", qVersion()}, {"qt_build_version", QT_VERSION_STR},
            {"main_thread", QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread()},
            {"scene_review_required", review_.required()}, {"preview_modes", QJsonArray{"native", "snapshot"}},
            {"preview", QJsonObject{{"enabled", previewEnabled_}, {"mode", snapshotPath_.isEmpty() ? "native" : "snapshot"},
                {"refresh_requests", refreshRequests_}, {"snapshot_calls", previewSnapshotCalls_}}}};
    }};
    registry_["stop_bridge"] = {Access::Control, [](auto&, const auto&) { return QJsonObject{{"stopped", true}}; }};
    registry_["refresh_view"] = {Access::Control, [this](auto&, const auto&) { return refresh(); }};
    registry_["set_live_preview"] = {Access::Control, [this](auto&, const auto& p) {
        bool enabled = boolValue(p, "enabled", true);
        QString path;
        if (p.contains("path") && !p["path"].isNull() && p["path"] != QJsonValue("")) path = outputPath(p, "path");
        previewEnabled_ = enabled; snapshotPath_ = path;
        return QJsonObject{{"live_preview", enabled}, {"snapshot_path", path.isEmpty() ? QJsonValue::Null : QJsonValue(path)},
                           {"preview_mode", path.isEmpty() ? "native" : "snapshot"}};
    }};
}
QJsonObject CommandDispatcher::refresh() {
    ++refreshRequests_;
    sdk_.Refresh3DWindow();
    if (snapshotPath_.isEmpty())
        return {{"refreshed", true}, {"repainted", false}, {"snapshot", QJsonValue::Null}, {"refresh_requested", true}, {"preview_mode", "native"}};
    Artifacts artifacts(snapshotPath_);
    ++previewSnapshotCalls_;
    auto paths = exportPaths(json(sdk_.ExportSnapshot3D(snapshotPath_.toStdString())));
    artifacts.verify(paths);
    return {{"refreshed", true}, {"repainted", true}, {"snapshot", paths.first()}, {"refresh_requested", true}, {"preview_mode", "snapshot"}};
}
QJsonObject CommandDispatcher::dispatch(const QJsonObject& request) noexcept {
    auto command = request["type"].toString(); auto id = request["id"];
    QJsonObject response{{"id", id}, {"status", "error"}};
    CommandContext context{sdk_, review_};
    QElapsedTimer time; time.start();
    auto uncertain = [&](const QString& message) {
        response["message"] = message;
        response["outcome"] = "unknown"; response["retry_safe"] = false; response["scene_review_required"] = true;
        response["review_persisted"] = review_.mark({{"command", command}, {"id", id}, {"reason", message}});
    };
    try {
        if (!request["type"].isString() || !request["params"].isObject()) throw ValidationError("Invalid command or parameters");
        if (!registry_.contains(command)) throw ValidationError(("Unsupported native command: " + command).toStdString());
        if (!sdk_.available()) throw std::runtime_error("CLO SDK interfaces are unavailable");
        auto params = request["params"].toObject(); auto entry = registry_.value(command);
        bool writes = entry.access != Access::Read && entry.access != Access::Control;
        bool recovery = entry.access == Access::Recovery && params["file_path"].isString()
            && QFileInfo(params["file_path"].toString()).suffix().compare("zprj", Qt::CaseInsensitive) == 0;
        if (review_.required() && writes && !recovery)
            throw OutcomeUnknown("A previous mutation needs scene review; inspect CLO and restore a distinct .zprj backup before more mutations");
        auto result = entry.handler(context, params);
        for (const auto* flag : {"opened", "saved", "exported", "imported", "created", "copied", "deleted", "simulated", "added", "replaced", "assigned", "set"})
            if (result.value(flag) == QJsonValue(false)) throw std::runtime_error(std::string("CLO reported ") + flag + "=false");
        if (previewEnabled_ && writes && context.entered) {
            try { refresh(); }
            catch (const std::exception& e) { result["preview_error"] = QString::fromUtf8(e.what()); }
            catch (...) { result["preview_error"] = "Unknown preview failure"; }
        }
        response["status"] = "success"; response["result"] = result;
    } catch (const OutcomeUnknown& e) { uncertain(QString::fromUtf8(e.what())); }
    catch (const std::exception& e) {
        if (context.entered) uncertain(QString::fromUtf8(e.what()));
        else response["message"] = QString::fromUtf8(e.what());
    } catch (...) {
        if (context.entered) uncertain("Unknown native exception after SDK dispatch");
        else response["message"] = "Unknown native exception";
    }
    // Bound the complete UTF-8 envelope before publication, while mutation
    // entry is still known. A large read must not become an uncertain edit.
    if (QJsonDocument(response).toJson(QJsonDocument::Compact).size() > MaxMessageBytes) {
        response = {{"id", id}, {"status", "error"}};
        const QString message = "JSON response exceeds 16 MiB limit";
        if (context.entered) uncertain(message + "; command may have been applied");
        else response["message"] = message;
    }
    if (response["status"] == "error" || debugLogging())
        log(directory_, QString("id=%1 command=%2 status=%3 sdk_validation_ms=%4 review=%5 message=%6")
            .arg(id.toString(), command, response["status"].toString()).arg(time.elapsed()).arg(review_.required())
            .arg(response["message"].toString().left(2048)));
    return response;
}
}
