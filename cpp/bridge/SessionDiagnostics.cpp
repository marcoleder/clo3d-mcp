#include "SessionDiagnostics.h"
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSysInfo>
#include <QUuid>
#include <stdexcept>

namespace clo::bridge {
namespace {
QString timestamp() { return QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs); }
}
void SessionDiagnostics::writeSession() {
    files_.write(QDir(directory_).filePath("native-session.json"), session_);
}
void SessionDiagnostics::writeCommand() {
    files_.write(QDir(directory_).filePath("last-command.json"), command_);
}
void SessionDiagnostics::start(const QString& session, QJsonObject metadata) noexcept {
    active_ = false;
    try {
        QDir directory(directory_);
        const auto previousPath = directory.filePath("native-session.json");
        const auto previous = files_.read(previousPath);
        if (QFileInfo::exists(previousPath) && previous["clean_shutdown"] != QJsonValue(true)) {
            // Preserve previous breadcrumbs and log rotations before this session
            // can overwrite them. A crash/kill is suspected, never diagnosed here.
            auto incident = directory.filePath("diagnostics/incidents/" + QUuid::createUuid().toString(QUuid::Id128));
            if (!QDir().mkpath(incident)) throw std::runtime_error("Cannot create incident directory");
            QStringList names{"native-session.json", "last-command.json", "bridge.log"};
            for (int i = 1; i <= LogBackups; ++i) names << "bridge.log." + QString::number(i);
            for (const auto& name : names) {
                const auto source = directory.filePath(name);
                if (QFileInfo::exists(source) && !QFile::copy(source, QDir(incident).filePath(name)))
                    throw std::runtime_error("Cannot preserve unclean-session evidence");
            }
            log(directory_, "preserved unclean session in " + incident);
        }
        session_ = {{"format", 1}, {"session", session}, {"backend", "cpp"}, {"protocol", 3},
            {"pid", QCoreApplication::applicationPid()}, {"host_executable", QCoreApplication::applicationFilePath()},
            {"host_version", QCoreApplication::applicationVersion()}, {"qt_version", qVersion()},
            {"os", QSysInfo::prettyProductName()}, {"architecture", QSysInfo::currentCpuArchitecture()},
            {"started_at", timestamp()}, {"clean_shutdown", false}, {"build", metadata}};
        // Keep per-session identity in both files: an interrupted reset cannot
        // associate an old command with the new process.
        command_ = {{"session", session}, {"phase", "idle"}, {"recorded_at", timestamp()}};
        writeSession(); writeCommand(); active_ = true;
    } catch (const std::exception& e) { log(directory_, "diagnostics start failed: " + QString::fromUtf8(e.what())); }
    catch (...) { log(directory_, "diagnostics start failed"); }
}
void SessionDiagnostics::beforeCommand(const QJsonObject& request) noexcept {
    if (!active_) return;
    try {
        command_ = {{"session", session_["session"]}, {"id", request["id"]},
            {"command", request["type"].toString().left(128)}, {"phase", "dispatching"}, {"recorded_at", timestamp()}};
        writeCommand(); // Params/garment data are deliberately absent.
    } catch (...) { log(directory_, "cannot record command-start breadcrumb"); }
}
void SessionDiagnostics::afterCommand(const QJsonObject& response) noexcept {
    if (!active_) return;
    try {
        command_["phase"] = "sdk_returned"; // Publication happens later in ProtocolQueue.
        command_["status"] = response["status"]; command_["recorded_at"] = timestamp();
        if (response.contains("outcome")) command_["outcome"] = response["outcome"];
        if (response.contains("message")) command_["message"] = response["message"].toString().left(2048);
        writeCommand();
    } catch (...) { log(directory_, "cannot record command-result breadcrumb"); }
}
void SessionDiagnostics::stop() noexcept {
    if (!active_) return;
    try { session_["clean_shutdown"] = true; session_["stopped_at"] = timestamp(); writeSession(); }
    catch (...) { log(directory_, "cannot record clean shutdown"); }
    active_ = false;
}
}
