#pragma once
#include "ResultContracts.h"
#include "SceneReviewState.h"
#include "SdkAdapter.h"
#include <QMap>

namespace clo::bridge {
enum class Access { Read, Mutation, ArtifactWrite, ProjectWrite, Recovery, Control };
struct CommandContext {
    SdkAdapter& sdk;
    SceneReviewState& review;
    bool entered = false;
    template<class F> decltype(auto) change(F&& f) { entered = true; return f(); }
};
using Handler = std::function<QJsonObject(CommandContext&, const QJsonObject&)>;
struct Command { Access access; Handler handler; };
using Registry = QMap<QString, Command>;
void addSceneHandlers(Registry& registry);
void addPatternHandlers(Registry& registry);
void addFabricHandlers(Registry& registry);
void addColorwayHandlers(Registry& registry);
void addAvatarHandlers(Registry& registry);
void addSimulationHandlers(Registry& registry);
void addExportHandlers(Registry& registry);
QJsonObject importAvatar(CommandContext&, const QJsonObject&);
QJsonObject addFabric(CommandContext&, const QJsonObject&);
QJsonArray patternList(SdkAdapter&);

class CommandDispatcher {
public:
    CommandDispatcher(SdkAdapter sdk, SceneReviewState& review, QString directory);
    QJsonObject dispatch(const QJsonObject& request) noexcept;
    const Registry& registry() const { return registry_; }
private:
    SdkAdapter sdk_;
    SceneReviewState& review_;
    QString directory_;
    Registry registry_;
    bool previewEnabled_ = false;
    QString snapshotPath_;
    qint64 refreshRequests_ = 0, previewSnapshotCalls_ = 0;
    QJsonObject refresh();
};
}
