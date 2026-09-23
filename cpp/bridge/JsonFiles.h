#pragma once
#include <QJsonObject>
#include <QString>
#include <functional>

namespace clo::bridge {
constexpr qint64 MaxMessageBytes = 16 * 1024 * 1024;
// Fault injection is confined to the reusable core, never controlled by IPC.
class JsonFiles {
public:
    std::function<void(const QString&, const QJsonObject&)> beforeWrite;
    QJsonObject read(const QString& path) const;
    void write(const QString& path, const QJsonObject& object) const;
    static bool remove(const QString& path) noexcept;
    static bool claim(const QString& pending, const QString& working) noexcept;
};
void log(const QString& directory, const QString& message) noexcept;
}
