"""Standard-library-only IPC shared with CLO's embedded Python interpreter."""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

PROTOCOL = 3
ACK_TIMEOUT = 5.0


def comm_directory():
    """Use one directory in the MCP server and CLO, regardless of TMPDIR.

    A custom CLO3D_MCP_DIR must be configured in both processes; the MCP
    client's server environment is not inherited by a separately launched CLO.
    """
    override = os.environ.get("CLO3D_MCP_DIR")
    if override:
        return override
    if sys.platform == "win32":
        return str(Path(os.environ.get("TEMP") or Path.home()) / "clo3d_mcp")
    users = Path("/mnt/c/Users")
    if sys.platform.startswith("linux") and users.is_dir():
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
    # MCP stdio filters POSIX temp variables; Dock-launched CLO retains them.
    return str(Path.home() / "clo3d_mcp")


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
        self._offered = None
        self._abandoned = set()

    def start(self, on_abandoned=None):
        for directory in (self.requests, self.responses):
            directory.mkdir(parents=True, exist_ok=True)
        # We hold the consumer lock, and have not published this session yet.
        # Clients from previous sessions can only receive an unknown outcome.
        claims = list(self.requests.glob("*.working"))
        removable = not claims or on_abandoned is None or on_abandoned(claims)
        for directory, patterns in ((self.responses, ("*.json",)),
                                    (self.requests, ("*.json", "*.ack"))):
            for pattern in patterns:
                for path in directory.glob(pattern):
                    self._remove(path)
        if removable:
            for path in claims:
                self._remove(path)
        else:
            self._abandoned.update(claims)
        atomic_json(self.ready, {"protocol": PROTOCOL, "session": self.session})

    def retire_abandoned(self):
        """Call only after preserving the review marker or verifying recovery."""
        for path in list(self._abandoned):
            self._remove(path)
            if not path.exists():
                self._abandoned.discard(path)

    @staticmethod
    def _remove(path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Locked orphan files must not prevent serving unrelated requests.
            pass

    def close(self):
        ready = read_json(self.ready)
        if isinstance(ready, dict) and ready.get("session") == self.session:
            self.ready.unlink(missing_ok=True)

    def process_one(self, dispatch):
        if self._offered is not None:
            request, claimed, token, started, deadline = self._offered
            request_id = request["id"]
            ack_path = claimed.with_suffix(".ack")
            ack = read_json(ack_path)
            valid = (isinstance(ack, dict) and ack.get("id") == request_id
                     and ack.get("session") == self.session and ack.get("token") == token)
            if valid:
                remaining = ack.get("timeout_seconds")
                valid = type(remaining) in (int, float) and math.isfinite(remaining) and remaining > 0
                if valid:
                    # Anchor the client's remaining duration to our earlier
                    # claim time, conservatively accounting for the handshake.
                    deadline = min(deadline, started + remaining)
            expired = time.monotonic() >= deadline
            if not expired and not valid:
                return False
            # Forget before calling native code or writing a result: neither a
            # failed dispatch nor a failed write may cause a replay next poll.
            self._offered = None
            self._remove(ack_path)
            try:
                if expired:
                    response = {"id": request_id, "status": "error",
                                "message": "Request acknowledgement expired before execution"}
                else:
                    response = json.loads(dispatch(json.dumps(request)))
                atomic_json(self.responses / (request_id + ".json"), response)
            except Exception:
                self._abandoned.add(claimed)
                raise
            # A failed review-marker write leaves the original durable claim as
            # evidence for the next bridge start, even if the client exits now.
            if response.get("review_persisted") is not False:
                self._remove(claimed)
            else:
                self._abandoned.add(claimed)
            return True
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
                timeout = request.get("timeout_seconds")
                if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                        or timeout <= 0):
                    error = "Invalid relative request timeout"
            if error:
                response = {"id": request_id, "status": "error", "message": error}
                atomic_json(response_path, response)
                self._remove(claimed)
            else:
                token = uuid.uuid4().hex
                # No wall-clock stamps cross the process/WSL boundary. A fresh
                # acknowledgement proves the client was still waiting at claim.
                started = time.monotonic()
                deadline = started + min(timeout, ACK_TIMEOUT)
                try:
                    atomic_json(response_path, {"id": request_id, "status": "claimed", "token": token})
                except Exception:
                    self._abandoned.add(claimed)
                    raise
                self._offered = (request, claimed, token, started, deadline)
            return True
        return False
