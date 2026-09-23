#include "ResultContracts.h"
#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <cmath>
#include <filesystem>
#include <functional>
#include <climits>

namespace clo::bridge {
namespace {
QJsonValue field(const QJsonObject& p, const char* key, const QJsonValue& fallback) {
    return p.contains(key) ? p[key] : fallback;
}
void invalid(const char* key) { throw ValidationError(std::string("Invalid or missing parameter: ") + key); }
}
QString stringValue(const QJsonObject& p, const char* key, QJsonValue fallback) {
    auto v = field(p, key, fallback);
    if (!v.isString() || v.toString().contains(QChar::Null)) invalid(key);
    return v.toString();
}
bool boolValue(const QJsonObject& p, const char* key, bool fallback) {
    auto v = field(p, key, fallback);
    if (!v.isBool()) invalid(key);
    return v.toBool();
}
qint64 integerValue(const QJsonValue& v, qint64 min, qint64 max, const char* name) {
    auto n = v.toDouble(std::numeric_limits<double>::quiet_NaN());
    if (!v.isDouble() || !std::isfinite(n) || std::trunc(n) != n || n < min || n > max) invalid(name);
    return static_cast<qint64>(n);
}
qint64 integer(const QJsonObject& p, const char* key, qint64 min, qint64 max, QJsonValue fallback) {
    return integerValue(field(p, key, fallback), min, max, key);
}
float numberValue(const QJsonValue& v, const char* name) {
    double n = v.toDouble(std::numeric_limits<double>::quiet_NaN());
    if (!v.isDouble() || !std::isfinite(n) || std::abs(n) > std::numeric_limits<float>::max()
        || (n != 0 && static_cast<float>(n) == 0)) invalid(name);
    return static_cast<float>(n);
}
int index(const QJsonObject& p, const char* key, qint64 count) { return static_cast<int>(integer(p, key, 0, std::min<qint64>(count - 1, INT_MAX))); }
QString outputPath(const QJsonObject& p, const char* key) {
    auto path = stringValue(p, key);
    if (path.trimmed().isEmpty() || !QFileInfo(path).isAbsolute() || QFileInfo(path).isDir()) invalid(key);
    if (!QFileInfo(QFileInfo(path).absolutePath()).isDir()) throw ValidationError("Output parent directory does not exist");
    return path;
}
QString inputPath(const QJsonObject& p, const char* key) {
    auto path = stringValue(p, key);
    if (!QFileInfo(path).isAbsolute() || !QFileInfo(path).isFile()) throw ValidationError("Input must be an existing absolute file path");
    return path;
}
bool samePath(const QString& a, const QString& b) {
    if (a.isEmpty() || b.isEmpty()) return false;
    std::error_code ec;
#ifdef _WIN32
    auto pa = std::filesystem::path(a.toStdWString()), pb = std::filesystem::path(b.toStdWString());
#else
    auto pa = std::filesystem::u8path(a.toStdString()), pb = std::filesystem::u8path(b.toStdString());
#endif
    if (std::filesystem::equivalent(pa, pb, ec) && !ec) return true;
    auto norm = [](const QString& p) {
        QFileInfo info(p);
        auto s = info.canonicalFilePath();
        if (s.isEmpty()) s = QDir::cleanPath(info.absoluteFilePath());
#ifdef _WIN32
        s = s.toCaseFolded();
#endif
        return s;
    };
    return norm(a) == norm(b);
}
QJsonValue parseSdkJson(const std::string& text, QJsonValue empty) {
    if (text.empty()) return empty;
    // Wrapping permits scalar JSON as well as objects/arrays.
    QJsonParseError error;
    auto doc = QJsonDocument::fromJson("[" + QByteArray::fromStdString(text) + "]", &error);
    return error.error == QJsonParseError::NoError ? doc.array().at(0)
        : QJsonValue(QJsonObject{{"raw", QString::fromStdString(text)}});
}
QJsonArray exportPaths(const QJsonValue& value) {
    QJsonArray paths;
    std::function<void(const QJsonValue&)> visit = [&](const QJsonValue& v) {
        if (v.isString() && !v.toString().trimmed().isEmpty()) paths.append(v);
        else if (v.isArray()) for (const auto& child : v.toArray()) visit(child);
        else throw std::runtime_error("CLO returned an invalid output path");
    };
    visit(value);
    if (paths.isEmpty()) throw std::runtime_error("CLO returned no output paths");
    return paths;
}
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
}
