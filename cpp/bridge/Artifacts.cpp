#include "Artifacts.h"
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QImageReader>
#include <QJsonDocument>
#include <QUrl>
#include <QtEndian>
#include <filesystem>

namespace clo::bridge {
Artifacts::Stamp Artifacts::stamp(const QString& path) {
#ifdef _WIN32
    auto p = std::filesystem::path(path.toStdWString());
#else
    auto p = std::filesystem::u8path(path.toStdString());
#endif
    std::error_code ec;
    auto modified = std::filesystem::last_write_time(p, ec);
    if (ec) throw ValidationError("Cannot inspect existing artifact timestamp");
    return {modified.time_since_epoch().count(), QFileInfo(path).size()};
}
Artifacts::Artifacts(const QString& target) {
    QDirIterator it(QFileInfo(target).absolutePath(), QDir::Files | QDir::NoDotAndDotDot, QDirIterator::Subdirectories);
    int count = 0;
    while (it.hasNext()) {
        auto path = it.next();
        if (++count > 10000) throw ValidationError("Output directory exceeds 10000 files; use a dedicated export directory");
        before_[QFileInfo(path).absoluteFilePath()] = stamp(path);
    }
}
QJsonObject Artifacts::readObject(const QString& path) {
    QFile f(path);
    require(f.open(QIODevice::ReadOnly), "Cannot read exported JSON");
    QJsonParseError error;
    auto doc = QJsonDocument::fromJson(f.readAll(), &error);
    require(error.error == QJsonParseError::NoError && doc.isObject(), "Invalid JSON artifact");
    return doc.object();
}
void Artifacts::verify(const QJsonArray& paths, QSize imageSize, bool requireFresh) const {
    require(!paths.isEmpty(), "CLO returned no output paths");
    for (const auto& value : paths) {
        auto path = value.toString(); QFileInfo info(path);
        require(info.isFile() && info.size() > 0, "CLO did not produce all nonempty output files");
        auto key = info.absoluteFilePath();
        if (requireFresh && before_.contains(key) && before_[key] == stamp(path))
            throw std::runtime_error(("CLO did not update an existing output file: " + path).toStdString());
        QFile file(path); require(file.open(QIODevice::ReadOnly), "Cannot read output file");
        auto head = file.peek(32); auto ext = info.suffix().toLower();
        if (ext == "png" || ext == "jpg" || ext == "jpeg") {
            QImageReader reader(path);
            require(reader.canRead() && reader.size().isValid(), "Invalid image artifact");
            if (imageSize.isValid()) require(reader.size() == imageSize, "Turntable dimensions differ from request");
        } else if (ext == "obj") {
            bool vertices = false, faces = false;
            while (!(vertices && faces) && !file.atEnd()) { auto line = file.readLine(); vertices |= line.startsWith("v "); faces |= line.startsWith("f "); }
            require(vertices && faces, "OBJ has no geometry");
        } else if (ext == "fbx") {
            require(head.startsWith("Kaydara FBX Binary") || head.startsWith("; FBX"), "Invalid FBX header");
        } else if (ext == "glb") {
            require(head.size() >= 20 && head.startsWith("glTF"), "Invalid GLB header");
            auto word = [&](int offset) { return qFromLittleEndian<quint32>(head.constData() + offset); };
            require(word(4) == 2 && word(8) == static_cast<quint64>(info.size()) && word(16) == 0x4e4f534a
                    && word(12) <= info.size() - 20, "Invalid GLB length/version");
            file.seek(20);
            auto root = QJsonDocument::fromJson(file.read(word(12))).object();
            require(!root["meshes"].toArray().isEmpty(), "GLB has no meshes");
        } else if (ext == "gltf") {
            auto root = readObject(path);
            require(root["asset"].toObject()["version"] == "2.0" && !root["meshes"].toArray().isEmpty(), "Invalid glTF or no meshes");
            for (const auto* group : {"buffers", "images"}) for (const auto& item : root[group].toArray()) {
                auto uri = item.toObject()["uri"].toString();
                if (uri.isEmpty() || uri.startsWith("data:")) continue;
                auto resource = info.dir().filePath(QUrl::fromPercentEncoding(uri.toUtf8()));
                require(QFileInfo(resource).isFile() && QFileInfo(resource).size() > 0, "Missing glTF resource");
            }
        } else if (ext == "json") {
            readObject(path);
        } else if (ext == "zprj" || ext == "zpac" || ext == "zip") {
            // CLO prepends a proprietary header to its ZIP payload. Locate the
            // central directory from the end record, as self-extracting ZIPs do.
            file.seek(std::max<qint64>(0, file.size() - 65557));
            auto tail = file.readAll(); auto end = tail.lastIndexOf(QByteArray("PK\005\006", 4));
            require(end >= 0 && end + 22 <= tail.size(), "Missing CLO/ZIP end record");
            auto record = tail.constData() + end;
            auto entries = qFromLittleEndian<quint16>(record + 10);
            auto size = qFromLittleEndian<quint32>(record + 12);
            auto comment = qFromLittleEndian<quint16>(record + 20);
            require(entries > 0 && size > 0 && end + 22 + comment == tail.size()
                    && size <= file.size() - 22 - comment, "Invalid CLO/ZIP central directory");
            file.seek(file.size() - 22 - comment - size);
            require(file.read(4) == QByteArray("PK\001\002", 4), "Invalid CLO/ZIP directory signature");
        }
    }
}
}
