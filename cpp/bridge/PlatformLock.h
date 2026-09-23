#pragma once

#include <QString>

namespace clo::bridge {
// Uses the same OS lock as Python ipc.bridge_lock; the file is never unlinked.
class PlatformLock {
public:
    PlatformLock() = default;
    ~PlatformLock();
    PlatformLock(const PlatformLock&) = delete;
    PlatformLock& operator=(const PlatformLock&) = delete;
    void acquire(const QString& directory);
    void release() noexcept;
private:
#ifdef _WIN32
    void* handle_ = nullptr;
#else
    int fd_ = -1;
#endif
};
QString commDirectory();
}
