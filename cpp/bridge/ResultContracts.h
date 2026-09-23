#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <limits>
#include <climits>
#include <map>
#include <stdexcept>
#include <vector>

namespace clo::bridge {
struct ValidationError : std::runtime_error { using std::runtime_error::runtime_error; };
struct OutcomeUnknown : std::runtime_error { using std::runtime_error::runtime_error; };
QString stringValue(const QJsonObject& p, const char* key, QJsonValue fallback = {});
bool boolValue(const QJsonObject& p, const char* key, bool fallback);
qint64 integerValue(const QJsonValue& value, qint64 min, qint64 max, const char* name);
qint64 integer(const QJsonObject& p, const char* key, qint64 min = 0,
               qint64 max = std::numeric_limits<int>::max(), QJsonValue fallback = {});
float numberValue(const QJsonValue& value, const char* name);
int index(const QJsonObject& p, const char* key, qint64 count);
QString inputPath(const QJsonObject& p, const char* key = "file_path");
QString outputPath(const QJsonObject& p, const char* key = "file_path");
bool samePath(const QString& a, const QString& b);
QJsonValue parseSdkJson(const std::string& text, QJsonValue empty = QJsonObject{});
inline QJsonValue json(const std::string& v) { return QString::fromStdString(v); }
inline QJsonValue json(int v) { return v; }
inline QJsonValue json(unsigned v) { return static_cast<qint64>(v); }
inline QJsonValue json(const std::map<std::string, std::string>& value) {
    QJsonObject result;
    for (const auto& [k, v] : value) result[QString::fromStdString(k)] = json(v);
    return result;
}
template<class T> QJsonValue json(const std::vector<T>& value) {
    QJsonArray result;
    for (const auto& v : value) result.append(json(v));
    return result;
}
QJsonArray exportPaths(const QJsonValue& value);
void require(bool condition, const char* message);
}
