#pragma once
#include "ResultContracts.h"
#include <QMap>
#include <QSize>

namespace clo::bridge {
// Capture before entering the SDK so unchanged old exports cannot pass.
class Artifacts {
public:
    explicit Artifacts(const QString& target);
    void verify(const QJsonArray& paths, QSize imageSize = {}, bool requireFresh = true) const;
    static QJsonObject readObject(const QString& path);
private:
    using Stamp = std::pair<qint64, qint64>;
    QMap<QString, Stamp> before_;
    static Stamp stamp(const QString& path);
};
}
