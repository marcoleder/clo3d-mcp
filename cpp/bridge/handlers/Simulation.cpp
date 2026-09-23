#include "CommandDispatcher.h"

namespace clo::bridge {
void addSimulationHandlers(Registry& r) {
    r["simulate"] = {Access::Mutation, [](auto& c, const auto& p) {
        auto steps = integer(p, "steps", 0, std::numeric_limits<unsigned>::max(), 100);
        require(c.change([&] { return c.sdk.Simulate(static_cast<unsigned>(steps)); }), "Simulate returned false");
        return QJsonObject{{"simulated", true}, {"steps", steps}};
    }};
    r["set_simulation_quality"] = {Access::Mutation, [](auto& c, const auto& p) {
        int quality = integer(p, "quality", 0, 3), mode = integer(p, "simulation_mode", 0, 1, 0);
        c.change([&] { c.sdk.SetSimulationQuality(quality, mode); });
        require(c.sdk.GetSimulationQuality() == std::make_pair(quality, mode), "Simulation quality readback failed");
        return QJsonObject{{"quality", quality}, {"simulation_mode", mode}};
    }};
}
}
