#pragma once
#include "PlatformLock.h"
#include "ProtocolQueue.h"
#include "SessionDiagnostics.h"
#include <QObject>
#include <QTimer>

namespace clo::bridge {
// SDK integration is injected; the controller/transport never depends on CLO.
class BridgeController : public QObject {
public:
    enum class State { Stopped, Starting, Serving, Stopping };
    BridgeController(QString directory, QObject* parent = nullptr);
    ~BridgeController() override;
    void start();
    void stop() noexcept;
    void tick() noexcept;
    State state() const { return state_; }
    SceneReviewState& review() { return review_; }
    JsonFiles& files() { return files_; }
    QString session() const { return queue_.session(); }
    ProtocolQueue::Dispatch dispatch;
    std::function<bool()> available = [] { return true; };
    std::function<bool()> deferred = [] { return false; };
    QJsonObject buildMetadata;
private:
    QString directory_;
    PlatformLock lock_;
    JsonFiles files_;
    SceneReviewState review_;
    ProtocolQueue queue_;
    SessionDiagnostics diagnostics_;
    QTimer timer_;
    State state_ = State::Stopped;
    bool executing_ = false;
    void finishStop() noexcept;
};
}
