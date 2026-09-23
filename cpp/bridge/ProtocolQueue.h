#pragma once
#include "JsonFiles.h"
#include "SceneReviewState.h"
#include <QDirIterator>
#include <chrono>
#include <functional>
#include <memory>
#include <optional>

namespace clo::bridge {
class ProtocolQueue {
public:
    using Clock = std::chrono::steady_clock;
    using Dispatch = std::function<QJsonObject(const QJsonObject&)>;
    ProtocolQueue(QString directory, JsonFiles& files, SceneReviewState& review);
    void start(); // Caller holds PlatformLock until close().
    void tick(const Dispatch& dispatch, bool deferred = false);
    void close() noexcept;
    bool ready() const { return phase_ == Phase::Serving; }
    QString session() const { return session_; }
    std::function<Clock::time_point()> now = [] { return Clock::now(); };
private:
    enum class Phase { Closed, Recover, Requests, Responses, Serving };
    struct Offer {
        QJsonObject request;
        QString claim, token;
        Clock::time_point started, deadline;
    };
    QString directory_, requests_, responses_, readyPath_, session_;
    JsonFiles& files_;
    SceneReviewState& review_;
    Phase phase_ = Phase::Closed;
    std::unique_ptr<QDirIterator> scan_;
    std::unique_ptr<QDirIterator> retire_;
    std::optional<Offer> offer_;
    void scan(const QString& path);
    void initializeTick();
    void retireTick();
    void complete(const Offer& offer, const QJsonObject& response);
    void reject(const Offer& offer, const QString& reason);
};
}
