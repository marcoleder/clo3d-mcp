#include "BridgeController.h"
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QScopedValueRollback>
#include <QThread>
#include <stdexcept>

namespace clo::bridge {
BridgeController::BridgeController(QString directory, QObject* parent)
    : QObject(parent), directory_(std::move(directory)), review_(directory_, files_), queue_(directory_, files_, review_) {
    timer_.setInterval(50);
    connect(&timer_, &QTimer::timeout, this, [this] { tick(); });
    if (auto app = QCoreApplication::instance())
        connect(app, &QCoreApplication::aboutToQuit, this, [this] { stop(); }, Qt::DirectConnection);
}
BridgeController::~BridgeController() { finishStop(); }
void BridgeController::start() {
    if (QThread::currentThread() != thread() || !QCoreApplication::instance()
        || thread() != QCoreApplication::instance()->thread())
        throw std::runtime_error("The native bridge must start on the application thread");
    if (state_ != State::Stopped) return;
    state_ = State::Starting;
    try {
        if (!available()) throw std::runtime_error("CLO SDK interfaces are unavailable");
        lock_.acquire(directory_);
        if (!JsonFiles::remove(QDir(directory_).filePath("stop"))) throw std::runtime_error("Cannot clear stale stop sentinel");
        queue_.start();
        timer_.start();
        log(directory_, "start returned; native timer owns service");
    } catch (...) { finishStop(); throw; }
}
void BridgeController::stop() noexcept {
    if (state_ == State::Stopped) return;
    state_ = State::Stopping;
    if (!executing_) finishStop();
}
void BridgeController::finishStop() noexcept {
    timer_.stop();
    queue_.close();
    state_ = State::Stopped;
    lock_.release(); // Last: no callback can consume another command after this.
}
void BridgeController::tick() noexcept {
    if (executing_ || state_ == State::Stopped) return;
    {
        QScopedValueRollback<bool> guard(executing_, true);
        try {
            auto sentinel = QDir(directory_).filePath("stop");
            if (QFileInfo::exists(sentinel)) { JsonFiles::remove(sentinel); stop(); }
            if (state_ != State::Stopping) {
                queue_.tick([this](const QJsonObject& request) {
                    if (!available()) throw std::runtime_error("CLO SDK interfaces became unavailable");
                    auto response = dispatch(request);
                    if (request["type"] == "stop_bridge" && response["status"] == "success") stop();
                    return response;
                }, deferred());
                if (queue_.ready() && state_ == State::Starting) state_ = State::Serving;
            }
        } catch (const std::exception& e) {
            review_.mark({{"command", "bridge_io"}, {"reason", QString::fromUtf8(e.what())}});
            log(directory_, "tick failed; no replay: " + QString::fromUtf8(e.what()));
        } catch (...) {
            review_.mark({{"command", "bridge_io"}, {"reason", "Unknown native exception"}});
            log(directory_, "tick failed; unknown exception; no replay");
        }
    }
    if (state_ == State::Stopping) finishStop();
}
}
