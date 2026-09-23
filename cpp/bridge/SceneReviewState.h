#pragma once
#include "JsonFiles.h"

namespace clo::bridge {
class SceneReviewState {
public:
    SceneReviewState(QString directory, JsonFiles& files);
    bool required() const;
    bool mark(const QJsonObject& details) noexcept;
    bool persist() noexcept;
    void clear(); // Only after a verified, distinct-project recovery.
private:
    QString path_;
    JsonFiles& files_;
    QJsonObject details_;
};
}
