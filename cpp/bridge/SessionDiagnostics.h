#pragma once
#include "JsonFiles.h"

namespace clo::bridge {
// Ordinary application-thread writes, never a signal/exception handler.
// Failures are logged and cannot prevent bridge work or manufacture scene review.
class SessionDiagnostics {
public:
    explicit SessionDiagnostics(QString directory) : directory_(std::move(directory)) {}
    void start(const QString& session, QJsonObject metadata = {}) noexcept;
    void beforeCommand(const QJsonObject& request) noexcept;
    void afterCommand(const QJsonObject& response) noexcept;
    void stop() noexcept;
private:
    QString directory_;
    JsonFiles files_;
    QJsonObject session_, command_;
    bool active_ = false;
    void writeSession();
    void writeCommand();
};
}
