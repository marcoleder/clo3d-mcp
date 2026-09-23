#include "TestSupport.h"
#include "SessionDiagnostics.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QTemporaryDir>

using namespace clo::bridge;
void write(const QString& path, const QByteArray& data) {
    QFile file(path); CHECK(file.open(QIODevice::WriteOnly)); CHECK(file.write(data) == data.size());
}
QByteArray read(const QString& path) {
    QFile file(path); CHECK(file.open(QIODevice::ReadOnly)); return file.readAll();
}
int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    try {
        {
            QTemporaryDir dir; auto path = dir.filePath("bridge.log");
            for (int i = 0; i < LogBackups + 3; ++i) {
                write(path, QByteArray(MaxLogBytes, '0' + i));
                log(dir.path(), "rotated");
                CHECK(QFileInfo(path).size() < MaxLogBytes);
            }
            auto files = QDir(dir.path()).entryList(QDir::Files);
            CHECK(files.size() == LogBackups + 1);
            for (int i = 1; i <= LogBackups; ++i) {
                auto bytes = read(path + "." + QString::number(i));
                CHECK(bytes.size() == MaxLogBytes && bytes.front() == '0' + LogBackups + 3 - i);
            }
            log(dir.path(), QString(MaxLogBytes, 'x') + "\nforged line");
            CHECK(QFileInfo(path).size() < 20000); // One oversized record is capped.
        }
        {
            QTemporaryDir dir; auto path = dir.filePath("bridge.log");
            write(path, QByteArray(MaxLogBytes, 'x'));
            CHECK(QDir().mkdir(path + ".3")); // Simulate locked/nonreplaceable backup.
            log(dir.path(), "must not grow"); CHECK(QFileInfo(path).size() == MaxLogBytes);
        }
        {
            QTemporaryDir dir; JsonFiles files;
            SessionDiagnostics first(dir.path());
            first.start("first", {{"binary_sha256", "build-id"}});
            first.beforeCommand({{"id", "command-id"}, {"type", "copy_colorway"}, {"params", QJsonObject{{"secret", "garment-secret"}}}});
            log(dir.path(), "previous session log");
            CHECK(!read(dir.filePath("last-command.json")).contains("garment-secret"));
            // Do not stop: equivalent on-disk state to an abrupt process exit.
            SessionDiagnostics next(dir.path()); next.start("second");
            QDir incidents(dir.filePath("diagnostics/incidents"));
            auto names = incidents.entryList(QDir::Dirs | QDir::NoDotAndDotDot); CHECK(names.size() == 1);
            QDir incident(incidents.filePath(names.first()));
            CHECK(files.read(incident.filePath("native-session.json"))["session"] == "first");
            CHECK(files.read(incident.filePath("last-command.json"))["phase"] == "dispatching");
            CHECK(read(incident.filePath("bridge.log")).contains("previous session log"));
            CHECK(files.read(dir.filePath("native-session.json"))["session"] == "second");
            next.beforeCommand({{"id", "read"}, {"type", "get_pattern_list"}});
            next.afterCommand({{"status", "error"}, {"message", "example SDK failure"}});
            auto command = files.read(dir.filePath("last-command.json"));
            CHECK(command["phase"] == "sdk_returned" && command["message"] == "example SDK failure");
            next.stop(); CHECK(files.read(dir.filePath("native-session.json"))["clean_shutdown"] == true);
            next.start("third"); next.stop();
            CHECK(incidents.entryList(QDir::Dirs | QDir::NoDotAndDotDot).size() == 1);
        }
        {
            QTemporaryDir dir; JsonFiles files;
            files.write(dir.filePath("native-session.json"), {{"session", "preserve"}, {"clean_shutdown", false}});
            write(dir.filePath("diagnostics"), "blocked directory");
            SessionDiagnostics blocked(dir.path()); blocked.start("new");
            blocked.beforeCommand({{"type", "test"}}); blocked.stop(); // No exceptions escape.
            CHECK(files.read(dir.filePath("native-session.json"))["session"] == "preserve");
        }
        std::cout << "Bounded logs, rotation faults, crash breadcrumbs and incident preservation passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
