#include "TestSupport.h"
#include "BridgeController.h"
#include <QCoreApplication>
#include <QDir>
#include <QTemporaryDir>
#include <QThread>
#include <QUuid>

using namespace clo::bridge;
struct Fixture {
    QTemporaryDir directory;
    JsonFiles files;
    SceneReviewState review{directory.path(), files};
    ProtocolQueue queue{directory.path(), files, review};
    ProtocolQueue::Clock::time_point clock{std::chrono::seconds(100)};
    int calls = 0;
    Fixture() { queue.now = [&] { return clock; }; queue.start(); start(); }
    QString path(const QString& name) { return QDir(directory.path()).filePath(name); }
    QJsonObject dispatch(const QJsonObject& q) { ++calls; return {{"id", q["id"]}, {"status", "success"}, {"result", QJsonObject{{"calls", calls}}}}; }
    void tick(bool deferred = false) { queue.tick([&](const auto& q) { return dispatch(q); }, deferred); }
    void start() { for (int i = 0; !queue.ready() && i < 100; ++i) tick(); CHECK(queue.ready()); }
    QString submit(double timeout = 5) {
        auto id = QUuid::createUuid().toString(QUuid::Id128);
        files.write(path("requests/" + id + ".json"), {{"protocol", 3}, {"id", id}, {"session", queue.session()}, {"type", "mutate"}, {"params", QJsonObject{}}, {"timeout_seconds", timeout}});
        return id;
    }
    void offer(const QString& id) { for (int i = 0; i < 4 && response(id).isEmpty(); ++i) tick(); CHECK(response(id)["status"] == "claimed"); }
    QJsonObject response(const QString& id) { return files.read(path("responses/" + id + ".json")); }
    void ack(const QString& id, QJsonValue remaining = 4) {
        files.write(path("requests/" + id + ".ack"), {{"id", id}, {"session", queue.session()}, {"token", response(id)["token"]}, {"timeout_seconds", remaining}});
    }
};
void checkControllerWriteFailures() {
    for (const QString stage : {"ready", "claimed", "rejected"}) for (bool standardException : {false, true}) {
        QTemporaryDir dir; BridgeController controller(dir.path()); JsonFiles files; int calls = 0, failures = 0;
        controller.dispatch = [&](const QJsonObject& request) {
            CHECK(!controller.review().required()); ++calls;
            return QJsonObject{{"id", request["id"]}, {"status", "success"}, {"result", QJsonObject{}}};
        };
        controller.files().beforeWrite = [&](const QString& path, const QJsonObject& object) {
            if ((stage == "ready" && path.endsWith("ready.json")) || object["status"] == stage
                || (stage == "rejected" && object["status"] == "error")) {
                ++failures;
                if (standardException) throw std::runtime_error("EACCES");
                throw 1;
            }
        };
        auto submit = [&](bool stale) {
            auto id = QUuid::createUuid().toString(QUuid::Id128);
            files.write(dir.filePath("requests/" + id + ".json"), {{"protocol", 3}, {"id", id},
                {"session", stale ? "stale" : controller.session()}, {"type", "mutate"},
                {"params", QJsonObject{}}, {"timeout_seconds", 4}});
            return id;
        };
        controller.start();
        for (int n = 0; n < 4; ++n) controller.tick();
        if (stage != "ready") {
            auto id = submit(stage == "rejected");
            for (int n = 0; n < 4 && !failures; ++n) controller.tick();
            CHECK(!QFileInfo::exists(dir.filePath("requests/" + id + ".working")));
        }
        CHECK(failures > 0 && calls == 0 && !controller.review().required());
        CHECK(!QFileInfo::exists(dir.filePath("scene-review-required.json")));
        controller.files().beforeWrite = {};
        // Retry readiness on the existing timer, then restart before any further
        // request cleanup to prove failed offers/rejections left no crash evidence.
        if (stage == "ready") { controller.tick(); CHECK(controller.state() == BridgeController::State::Serving); }
        controller.stop(); controller.start();
        for (int n = 0; n < 4; ++n) controller.tick();
        CHECK(!controller.review().required());
        auto id = submit(false); auto response = dir.filePath("responses/" + id + ".json");
        for (int n = 0; n < 4 && files.read(response).isEmpty(); ++n) controller.tick();
        CHECK(files.read(response)["status"] == "claimed");
        files.write(dir.filePath("requests/" + id + ".ack"), {{"id", id}, {"session", controller.session()},
            {"token", files.read(response)["token"]}, {"timeout_seconds", 4}});
        controller.tick(); CHECK(calls == 1 && files.read(response)["status"] == "success"); controller.stop();
    }
}
int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    try {
        checkControllerWriteFailures();
        for (bool failMarker : {false, true}) {
            Fixture f; auto id = f.submit(); f.offer(id); f.ack(id);
            f.files.beforeWrite = [=](const QString& path, const QJsonObject& object) {
                if (object["status"] == "success" || (failMarker && path.endsWith("scene-review-required.json"))) throw std::runtime_error("ENOSPC");
            };
            throws([&] { f.tick(); }); CHECK(f.calls == 1); CHECK(f.review.required());
            CHECK(QFileInfo::exists(f.path("requests/" + id + ".working")));
            f.tick(); CHECK(f.calls == 1);
            if (failMarker) CHECK(QFileInfo::exists(f.path("requests/" + id + ".working")));
            f.files.beforeWrite = {}; f.tick(); CHECK(f.review.persist());
        }
        {
            Fixture f; auto id = f.submit(); f.offer(id); f.ack(id);
            f.clock += std::chrono::seconds(1); f.tick(true); CHECK(f.calls == 0);
            f.clock += std::chrono::seconds(5); f.tick(true); CHECK(f.calls == 0);
            CHECK(f.response(id)["status"] == "error");
        }
        {
            Fixture f; auto id = f.submit(); f.offer(id); f.clock += std::chrono::seconds(6);
            f.files.beforeWrite = [](const auto&, const auto& response) { if (response["status"] == "error") throw std::runtime_error("ENOSPC"); };
            throws([&] { f.tick(); }); CHECK(f.calls == 0 && !f.review.required());
            CHECK(!QFileInfo::exists(f.path("requests/" + id + ".working")));
            f.files.beforeWrite = {}; f.queue.close(); f.queue.start(); f.start(); CHECK(!f.review.required());
        }
        for (const auto& remaining : {QJsonValue(true), QJsonValue(-1), QJsonValue("3"), QJsonValue(0)}) {
            Fixture f; auto id = f.submit(); f.offer(id); f.ack(id, remaining); f.tick(); CHECK(f.calls == 0);
            f.clock += std::chrono::seconds(6); f.tick(); CHECK(f.response(id)["status"] == "error");
        }
        {
            Fixture f; auto id = f.submit(); f.tick(true); CHECK(f.response(id).isEmpty());
            f.offer(id); f.ack(id, .01); f.clock += std::chrono::milliseconds(20); f.tick(); CHECK(f.calls == 0);
        }
        {
            Fixture f; auto id = f.submit(); f.offer(id); f.queue.close();
            f.files.write(f.path("requests/" + id + ".working"), {{"id", id}});
            f.files.beforeWrite = [](const QString& path, const QJsonObject&) { if (path.endsWith("scene-review-required.json")) throw std::runtime_error("EACCES"); };
            f.queue.start(); f.start(); CHECK(f.review.required()); CHECK(!f.review.persist());
            CHECK(QFileInfo::exists(f.path("requests/" + id + ".working")));
            f.files.beforeWrite = {}; f.tick(); CHECK(f.review.persist());
        }
        {
            Fixture f; f.files.write(f.path("ready.json"), {{"protocol", 3}, {"session", "other"}});
            f.queue.close(); CHECK(f.files.read(f.path("ready.json"))["session"] == "other");
        }
        {
            QTemporaryDir dir; BridgeController controller(dir.path()); int calls = 0;
            controller.dispatch = [&](const QJsonObject& request) {
                ++calls; controller.tick(); // Nested timer delivery while SDK/postconditions are active.
                return QJsonObject{{"id", request["id"]}, {"status", "success"}, {"result", QJsonObject{}}};
            };
            controller.start(); auto session = controller.session(); controller.start(); CHECK(controller.session() == session);
            for (int n = 0; n < 4; ++n) controller.tick();
            JsonFiles files; auto id = QUuid::createUuid().toString(QUuid::Id128);
            auto request = QDir(dir.path()).filePath("requests/" + id);
            auto response = QDir(dir.path()).filePath("responses/" + id + ".json");
            files.write(request + ".json", {{"protocol", 3}, {"id", id}, {"session", session}, {"type", "test"}, {"params", QJsonObject{}}, {"timeout_seconds", 4}});
            for (int n = 0; n < 4 && files.read(response).isEmpty(); ++n) controller.tick();
            files.write(request + ".ack", {{"id", id}, {"session", session}, {"token", files.read(response)["token"]}, {"timeout_seconds", 4}});
            controller.tick(); CHECK(calls == 1); controller.stop();
            PlatformLock lock; lock.acquire(dir.path()); lock.release();
            CHECK(!QFileInfo::exists(QDir(dir.path()).filePath("ready.json")));
            controller.start(); CHECK(controller.session() != session); controller.stop();
        }
        std::cout << "Native protocol faults, deadlines, recovery and reentrancy passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
