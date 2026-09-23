#include "ProtocolQueue.h"
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QRegularExpression>
#include <QUuid>
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace clo::bridge {
namespace {
constexpr int ScanBudget = 64;
QString uuid() { return QUuid::createUuid().toString(QUuid::Id128); }
bool duration(const QJsonValue& v) { return v.isDouble() && std::isfinite(v.toDouble()) && v.toDouble() > 0; }
QJsonObject error(const QString& id, const QString& message) {
    return {{"id", id}, {"status", "error"}, {"message", message}};
}
auto seconds(double value) {
    // Only the <=5 second offer window matters; avoid chrono overflow on huge inputs.
    return std::chrono::duration_cast<ProtocolQueue::Clock::duration>(std::chrono::duration<double>(std::min(value, 5.0)));
}
}
ProtocolQueue::ProtocolQueue(QString directory, JsonFiles& files, SceneReviewState& review)
    : directory_(std::move(directory)), requests_(QDir(directory_).filePath("requests")),
      responses_(QDir(directory_).filePath("responses")), readyPath_(QDir(directory_).filePath("ready.json")),
      files_(files), review_(review) {}
void ProtocolQueue::scan(const QString& path) {
    scan_ = std::make_unique<QDirIterator>(path, QDir::Files | QDir::NoDotAndDotDot);
}
void ProtocolQueue::start() {
    if (phase_ != Phase::Closed) return;
    if (!QDir().mkpath(requests_) || !QDir().mkpath(responses_))
        throw std::runtime_error("Cannot create IPC request/response directories");
    // Under the lock, invalidate previous readiness before asynchronous recovery.
    if (!JsonFiles::remove(readyPath_)) throw std::runtime_error("Cannot remove stale readiness");
    session_ = uuid();
    offer_.reset();
    retire_.reset();
    phase_ = Phase::Recover;
    scan(requests_);
}
void ProtocolQueue::initializeTick() {
    int budget = ScanBudget;
    while (budget-- && scan_->hasNext()) {
        auto path = scan_->next();
        auto suffix = scan_->fileInfo().suffix();
        if (phase_ == Phase::Recover && suffix == "working") {
            review_.mark({{"command", "bridge_restart"}, {"reason", "Abandoned request outcome is unknown"}});
        } else if (phase_ == Phase::Requests && (suffix == "json" || suffix == "ack")) {
            JsonFiles::remove(path);
        } else if (phase_ == Phase::Requests && suffix == "working" && review_.persist()) {
            JsonFiles::remove(path);
        } else if (phase_ == Phase::Responses && suffix == "json") {
            JsonFiles::remove(path);
        }
    }
    if (scan_->hasNext()) return;
    if (phase_ == Phase::Recover) { phase_ = Phase::Requests; scan(requests_); }
    else if (phase_ == Phase::Requests) { phase_ = Phase::Responses; scan(responses_); }
    else {
        files_.write(readyPath_, {{"protocol", 3}, {"session", session_}});
        phase_ = Phase::Serving;
        scan(requests_);
        log(directory_, "protocol 3 ready session=" + session_);
    }
}
void ProtocolQueue::retireTick() {
    if (review_.required() && !review_.persist()) return;
    if (!retire_) retire_ = std::make_unique<QDirIterator>(requests_, QDir::Files | QDir::NoDotAndDotDot);
    for (int n = 0; n < ScanBudget && retire_->hasNext(); ++n) {
        auto path = retire_->next();
        if (retire_->fileInfo().suffix() == "working" && (!offer_ || path != offer_->claim))
            JsonFiles::remove(path);
    }
    if (!retire_->hasNext()) retire_.reset();
}
void ProtocolQueue::complete(const Offer& offered, const QJsonObject& response) {
    auto id = offered.request["id"].toString();
    auto before = now();
    files_.write(QDir(responses_).filePath(id + ".json"), response);
    log(directory_, QString("session=%1 id=%2 status=%3 claim_to_response_ms=%4 publish_ms=%5")
        .arg(session_, id, response["status"].toString())
        .arg(std::chrono::duration<double, std::milli>(now() - offered.started).count())
        .arg(std::chrono::duration<double, std::milli>(now() - before).count()));
    if (response["review_persisted"] != QJsonValue(false)) JsonFiles::remove(offered.claim);
}
void ProtocolQueue::tick(const Dispatch& dispatch, bool deferred) {
    if (phase_ == Phase::Closed) return;
    if (phase_ != Phase::Serving) { initializeTick(); return; }
    retireTick();
    if (offer_) {
        const auto id = offer_->request["id"].toString();
        const auto ackPath = QDir(requests_).filePath(id + ".ack");
        const auto ack = files_.read(ackPath);
        bool valid = ack["id"] == id && ack["session"] == session_ && ack["token"] == offer_->token
            && duration(ack["timeout_seconds"]);
        if (valid) offer_->deadline = std::min(offer_->deadline, offer_->started + seconds(ack["timeout_seconds"].toDouble()));
        bool expired = now() >= offer_->deadline;
        if (!expired && (!valid || deferred)) return;
        // Consume permission before acknowledgement removal, SDK entry or publication.
        auto offered = std::move(*offer_);
        offer_.reset();
        if (!JsonFiles::remove(ackPath)) {
            complete(offered, error(id, "Cannot consume acknowledgement; request was not executed"));
            return;
        }
        if (expired || now() >= offered.deadline) {
            complete(offered, error(id, "Request acknowledgement expired before execution"));
            return;
        }
        try { complete(offered, dispatch(offered.request)); }
        catch (...) {
            review_.mark({{"command", "bridge_io"}, {"id", id}, {"reason", "Dispatch or terminal response failed; outcome unknown"}});
            throw;
        }
        return;
    }
    if (deferred) return; // Do not offer a handshake while the host is busy.
    QString pending;
    QDateTime oldest;
    static const QRegularExpression identifier("^[0-9a-f]{32}$");
    for (int n = 0; n < ScanBudget && scan_->hasNext(); ++n) {
        auto path = scan_->next();
        const auto info = scan_->fileInfo();
        if (info.suffix() != "json" || !identifier.match(info.completeBaseName()).hasMatch()) continue;
        if (pending.isEmpty() || info.lastModified() < oldest) { pending = path; oldest = info.lastModified(); }
    }
    // Restart next tick, without sorting or reading an unbounded directory.
    if (!scan_->hasNext()) scan(requests_);
    if (pending.isEmpty()) return;
    auto id = QFileInfo(pending).completeBaseName();
    auto claim = QDir(requests_).filePath(id + ".working");
    auto responsePath = QDir(responses_).filePath(id + ".json");
    if (QFileInfo::exists(claim) || QFileInfo::exists(responsePath)) { JsonFiles::remove(pending); return; }
    if (!JsonFiles::claim(pending, claim)) return; // A client may have timed out.
    auto request = files_.read(claim);
    QString reason;
    if (request["id"] != id) reason = "Invalid request envelope (maximum 16 MiB)";
    else if (request["protocol"] != QJsonValue(3) || request["session"] != session_)
        reason = "Bridge session changed; request was not executed";
    else if (!request["type"].isString() || !request["params"].isObject()) reason = "Invalid command or parameters";
    else if (!duration(request["timeout_seconds"])) reason = "Invalid relative request timeout";
    Offer offered{request, claim, uuid(), now(), {}};
    offered.request["id"] = id;
    if (!reason.isEmpty()) { complete(offered, error(id, reason)); return; }
    offered.deadline = offered.started + seconds(request["timeout_seconds"].toDouble());
    files_.write(responsePath, {{"id", id}, {"status", "claimed"}, {"token", offered.token}});
    offer_ = std::move(offered);
}
void ProtocolQueue::close() noexcept {
    try {
        if (files_.read(readyPath_)["session"] == session_) JsonFiles::remove(readyPath_);
    } catch (...) {}
    // An offered but unexecuted claim can be retired. Failed dispatched claims remain.
    if (offer_) JsonFiles::remove(offer_->claim);
    offer_.reset(); scan_.reset(); retire_.reset(); phase_ = Phase::Closed;
}
}
