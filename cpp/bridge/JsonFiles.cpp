#include "JsonFiles.h"
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QMutex>
#include <QMutexLocker>
#include <QSaveFile>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#else
#include <cstdio>
#endif

namespace clo::bridge {
QJsonObject JsonFiles::read(const QString& path) const {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly) || file.size() > MaxMessageBytes) return {};
    auto bytes = file.read(MaxMessageBytes + 1);
    if (bytes.size() > MaxMessageBytes) return {};
    return QJsonDocument::fromJson(bytes).object();
}
void JsonFiles::write(const QString& path, const QJsonObject& object) const {
    if (beforeWrite) beforeWrite(path, object);
    auto bytes = QJsonDocument(object).toJson(QJsonDocument::Compact);
    if (bytes.size() > MaxMessageBytes) throw std::runtime_error("JSON result exceeds 16 MiB limit");
    QSaveFile file(path);
    file.setDirectWriteFallback(false); // Never expose a partially written envelope.
    if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit())
        throw std::runtime_error(("Cannot atomically write " + path + ": " + file.errorString()).toStdString());
}
bool JsonFiles::remove(const QString& path) noexcept {
    return !QFileInfo::exists(path) || QFile::remove(path);
}
bool JsonFiles::claim(const QString& pending, const QString& working) noexcept {
    // QFile::rename may fall back to copy/delete. A durable claim must be one
    // atomic rename on the same filesystem, without that fallback.
#ifdef _WIN32
    return MoveFileExW(reinterpret_cast<LPCWSTR>(pending.utf16()),
                       reinterpret_cast<LPCWSTR>(working.utf16()), MOVEFILE_WRITE_THROUGH) != 0;
#else
    return ::rename(QFile::encodeName(pending).constData(), QFile::encodeName(working).constData()) == 0;
#endif
}
void log(const QString& directory, const QString& message) noexcept {
    try {
        static QMutex mutex;
        QMutexLocker guard(&mutex);
        if (!QDir().mkpath(directory)) return;
        const auto path = QDir(directory).filePath("bridge.log");
        // Bound even exception strings and reject forged multiline log entries.
        auto line = (QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)
            + " [cpp] " + message.left(4096).replace('\n', ' ').replace('\r', ' ') + '\n').toUtf8();
        if (QFileInfo(path).size() + line.size() > MaxLogBytes) {
            // If rotation fails (disk full/locked), skip logging instead of growing.
            if (!JsonFiles::remove(path + "." + QString::number(LogBackups))) return;
            for (int i = LogBackups - 1; i >= 0; --i) {
                auto from = i ? path + "." + QString::number(i) : path;
                if (QFileInfo::exists(from) && !QFile::rename(from, path + "." + QString::number(i + 1))) return;
            }
        }
        QFile file(path);
        if (file.open(QIODevice::WriteOnly | QIODevice::Append)) {
            file.write(line);
            file.flush(); // Close/flush on every record, including errors before a crash.
        }
    } catch (...) {} // Diagnostics cannot stop the service.
}
bool debugLogging() noexcept { return qEnvironmentVariableIntValue("CLO3D_MCP_DEBUG") == 1; }
}
