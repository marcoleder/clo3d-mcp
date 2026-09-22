"""Standard-library-only IPC shared with CLO's embedded Python interpreter."""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid

PROTOCOL = 2


def comm_directory():
    override = os.environ.get("CLO3D_MCP_DIR")
    if override:
        return override
    users = Path("/mnt/c/Users")
    if users.is_dir():
        try:
            candidates = [p / "AppData/Local/Temp/clo3d_mcp"
                          for p in sorted(users.iterdir()) if p.is_dir()
                          and p.name not in {"Public", "Default", "Default User", "All Users"}]
            for candidate in candidates:
                if candidate.is_dir():
                    return str(candidate)
            if candidates:
                return str(candidates[0])
        except OSError:
            pass
    return str(Path(os.environ.get("TEMP") or Path.home()) / "clo3d_mcp")


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None


@contextmanager
def bridge_lock(directory):
    """Only one consumer may dispatch CLO calls, including across processes."""
    Path(directory).mkdir(parents=True, exist_ok=True)
    with open(Path(directory) / "bridge.lock", "a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.write(b"\0")
            stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("A CLO bridge is already serving this directory") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("A CLO bridge is already serving this directory") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class BridgeQueue:
    """One-shot requests scoped to a bridge session; no replay after a crash.

    The caller must hold bridge_lock for this object's serving lifetime.
    Claimed files survive crashes so a restarted bridge cannot repeat a call
    whose outcome is unknown. Old sessions are never dispatched.
    """

    def __init__(self, directory):
        self.directory = Path(directory)
        self.requests = self.directory / "requests"
        self.responses = self.directory / "responses"
        self.ready = self.directory / "ready.json"
        self.session = uuid.uuid4().hex

    def start(self):
        for directory in (self.requests, self.responses):
            directory.mkdir(parents=True, exist_ok=True)
        atomic_json(self.ready, {"protocol": PROTOCOL, "session": self.session})

    def close(self):
        ready = read_json(self.ready)
        if isinstance(ready, dict) and ready.get("session") == self.session:
            self.ready.unlink(missing_ok=True)

    def process_one(self, dispatch):
        # Arrival order is best effort; disappearing files are client cancellations.
        def modified(path):
            try:
                return path.stat().st_mtime_ns
            except OSError:
                return 0
        for pending in sorted(self.requests.glob("*.json"), key=modified):
            request_id = pending.stem
            try:
                if uuid.UUID(request_id).hex != request_id:
                    continue
            except ValueError:
                continue
            claimed = pending.with_suffix(".working")
            response_path = self.responses / pending.name
            if claimed.exists() or response_path.exists():
                pending.unlink(missing_ok=True)
                continue
            try:
                pending.rename(claimed)
            except FileNotFoundError:
                continue
            request = read_json(claimed)
            error = None
            if not isinstance(request, dict) or request.get("id") != request_id:
                error = "Invalid request envelope"
            elif request.get("protocol") != PROTOCOL or request.get("session") != self.session:
                error = "Bridge session changed; request was not executed"
            else:
                expiry = request.get("expires_at")
                if (not isinstance(expiry, (int, float)) or not math.isfinite(expiry)
                        or time.time() >= expiry):
                    error = "Request expired before execution"
            if error:
                response = {"id": request_id, "status": "error", "message": error}
            else:
                response = json.loads(dispatch(json.dumps(request)))
            atomic_json(response_path, response)
            claimed.unlink()
            return True
        return False
