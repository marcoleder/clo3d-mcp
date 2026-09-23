// ABI verified against the full 2026.1.224 SDK Samples/ExportPlugin/ExportPlugin.h.
#include "BridgeController.h"
#include "CommandDispatcher.h"
#include <QApplication>
#include <QPointer>
#include <QThread>
#include <stdexcept>
#include <memory>
#ifdef _WIN32
#include <windows.h>
#define CLO_PLUGIN_EXPORT extern "C" __declspec(dllexport)
#else
#include <dlfcn.h>
#define CLO_PLUGIN_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {
using namespace clo::bridge;
QPointer<BridgeController> controller;
void pinLibrary() {
    // A process-lifetime reference prevents host Refresh/Remove from unloading
    // timer code. Deliberately never released: upgrading requires a CLO restart.
    static bool pinned = false;
    if (pinned) return;
#ifdef _WIN32
    HMODULE module = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                           reinterpret_cast<LPCWSTR>(&pinLibrary), &module))
        throw std::runtime_error("Cannot retain plugin library");
#else
    Dl_info info{};
    if (!dladdr(reinterpret_cast<void*>(&pinLibrary), &info) || !dlopen(info.dli_fname, RTLD_NOW | RTLD_LOCAL))
        throw std::runtime_error("Cannot retain plugin library");
#endif
    pinned = true;
}
}
CLO_PLUGIN_EXPORT void DoFunction() {
    try {
        auto app = QCoreApplication::instance();
        if (!app || QThread::currentThread() != app->thread())
            throw std::runtime_error("CLO menu callback did not run on the application thread");
        if (QString::fromLatin1(qVersion()) != QStringLiteral(QT_VERSION_STR))
            throw std::runtime_error("CLO Qt runtime does not match plugin build");
        pinLibrary();
        if (!controller) {
            controller = new BridgeController(commDirectory(), app);
            controller->available = hostSdk().available;
            controller->deferred = [] { return QApplication::activeModalWidget() != nullptr; };
        }
        if (controller->state() == BridgeController::State::Stopped) {
            auto dispatcher = std::make_shared<CommandDispatcher>(hostSdk(), controller->review(), commDirectory());
            controller->dispatch = [dispatcher](const auto& request) { return dispatcher->dispatch(request); };
        }
        controller->start();
    } catch (const std::exception& e) { log(commDirectory(), QString::fromUtf8(e.what())); }
    catch (...) { log(commDirectory(), "Native Start failed with unknown exception"); }
}
CLO_PLUGIN_EXPORT void DoFunctionAfterLoadingCLOFile(const char*) {} // No implicit start or scene access.
CLO_PLUGIN_EXPORT const char* GetActionName() { return "MCP Bridge (native C++)"; }
CLO_PLUGIN_EXPORT const char* GetObjectNameTreeToAddAction() { return "menuPlugins / menuPlug_In"; }
CLO_PLUGIN_EXPORT int GetPositionIndexToAddAction() { return 1; }
