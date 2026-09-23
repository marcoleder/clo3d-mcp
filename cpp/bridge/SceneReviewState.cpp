#include "SceneReviewState.h"
#include <QDir>
#include <QFileInfo>
#include <stdexcept>

namespace clo::bridge {
SceneReviewState::SceneReviewState(QString directory, JsonFiles& files)
    : path_(QDir(directory).filePath("scene-review-required.json")), files_(files) {}
bool SceneReviewState::required() const { return !details_.isEmpty() || QFileInfo::exists(path_); }
bool SceneReviewState::mark(const QJsonObject& details) noexcept {
    details_ = details_.isEmpty() ? details : details_;
    return persist();
}
bool SceneReviewState::persist() noexcept {
    if (QFileInfo::exists(path_)) return true; // Corrupt markers still block mutations.
    if (details_.isEmpty()) return false;
    try { files_.write(path_, details_); return true; } catch (...) { return false; }
}
void SceneReviewState::clear() {
    if (!JsonFiles::remove(path_)) throw std::runtime_error("Cannot clear scene review marker");
    details_ = {};
}
}
