#include "PlatformLock.h"
#include <QDir>
#include <QFile>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

namespace clo::bridge {
QString commDirectory() {
    auto override = qEnvironmentVariable("CLO3D_MCP_DIR");
    if (!override.isEmpty()) return override;
    auto base = qEnvironmentVariable("TEMP");
    return QDir(base.isEmpty() ? QDir::homePath() : base).filePath("clo3d_mcp");
}
PlatformLock::~PlatformLock() { release(); }
void PlatformLock::acquire(const QString& directory) {
    if (!QDir().mkpath(directory)) throw std::runtime_error("Cannot create IPC directory");
    auto path = QDir(directory).filePath("bridge.lock");
#ifdef _WIN32
    if (handle_) return;
    auto h = CreateFileW(reinterpret_cast<LPCWSTR>(path.utf16()), GENERIC_READ | GENERIC_WRITE,
                        FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    OVERLAPPED offset{};
    if (h == INVALID_HANDLE_VALUE) throw std::runtime_error("Cannot open bridge.lock");
    if (!LockFileEx(h, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &offset)) {
        CloseHandle(h);
        throw std::runtime_error("A CLO bridge is already serving this directory");
    }
    handle_ = h;
#else
    if (fd_ >= 0) return;
    int fd = ::open(QFile::encodeName(path).constData(), O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    if (fd < 0) throw std::runtime_error("Cannot open bridge.lock");
    if (flock(fd, LOCK_EX | LOCK_NB) != 0) {
        ::close(fd);
        throw std::runtime_error("A CLO bridge is already serving this directory");
    }
    fd_ = fd;
#endif
}
void PlatformLock::release() noexcept {
#ifdef _WIN32
    if (handle_) {
        OVERLAPPED offset{};
        UnlockFileEx(handle_, 0, 1, 0, &offset);
        CloseHandle(handle_);
        handle_ = nullptr;
    }
#else
    if (fd_ >= 0) { flock(fd_, LOCK_UN); ::close(fd_); fd_ = -1; }
#endif
}
}
