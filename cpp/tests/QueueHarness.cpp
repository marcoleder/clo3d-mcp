#include "BridgeController.h"
#include <QCoreApplication>
#include <QJsonArray>
#include <QThread>
#include <cstdio>

using namespace clo::bridge;
int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    if (argc != 2) { std::fprintf(stderr, "usage: clo_queue_harness IPC_DIRECTORY\n"); return 2; }
    BridgeController controller(QString::fromLocal8Bit(argv[1]));
    int calls = 0;
    controller.dispatch = [&](const QJsonObject& request) {
        auto command = request["type"].toString();
        QJsonObject result;
        if (command == "ping") result = {{"pong", true}, {"in_clo3d", false}, {"calls", calls}};
        else if (command == "stop_bridge") { result = {{"stopped", true}}; QTimer::singleShot(100, &app, &QCoreApplication::quit); }
        else if (controller.review().required())
            return QJsonObject{{"id", request["id"]}, {"status", "error"}, {"message", "Scene review required"},
                {"outcome", "unknown"}, {"retry_safe", false}, {"scene_review_required", true}, {"review_persisted", controller.review().persist()}};
        else {
            ++calls;
            if (command == "slow") QThread::msleep(400);
            result = {{"echo", request["params"]}, {"calls", calls}};
        }
        return QJsonObject{{"id", request["id"]}, {"status", "success"}, {"result", result}};
    };
    try { controller.start(); } catch (const std::exception& e) { std::fprintf(stderr, "%s\n", e.what()); return 1; }
    QTimer monitor;
    QObject::connect(&monitor, &QTimer::timeout, &app, [&] {
        if (controller.state() == BridgeController::State::Stopped) app.quit();
    });
    monitor.start(100);
    return app.exec();
}
