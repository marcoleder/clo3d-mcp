"""File IPC client. Each command is published once, with its own response file."""

from pathlib import Path
import time
import uuid

from .ipc import PROTOCOL, atomic_json, comm_directory, read_json

TIMEOUT = 180
PING_TIMEOUT = 5
POLL_INTERVAL = 0.05
_find_comm_dir = comm_directory


class CLO3DConnectionError(Exception):
    pass


class CLO3DConnection:
    def __init__(self, comm_dir=None):
        self.comm_dir = str(comm_dir or comm_directory())

    def _ready(self):
        ready = read_json(Path(self.comm_dir) / "ready.json")
        if (isinstance(ready, dict) and ready.get("protocol") == PROTOCOL
                and isinstance(ready.get("session"), str)):
            return ready
        return None

    @property
    def connected(self):
        """Readiness metadata exists. Use ping() to check actual responsiveness."""
        return self._ready() is not None

    def connect(self):
        if not self.connected:
            raise CLO3DConnectionError(
                f"No protocol-{PROTOCOL} CLO bridge ready at {self.comm_dir}. "
                "Start the updated bridge in CLO and use the same CLO3D_MCP_DIR on both sides."
            )

    def disconnect(self):
        """Clients do not own the shared bridge. Use stop_bridge to release CLO."""

    def send_command(self, command_type, params=None, *, timeout=None):
        if timeout is None:
            timeout = PING_TIMEOUT if command_type == "ping" else TIMEOUT
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        deadline = time.monotonic() + timeout
        startup_deadline = min(deadline, time.monotonic() + PING_TIMEOUT)
        ready = self._ready()
        while ready is None and time.monotonic() < startup_deadline:
            time.sleep(POLL_INTERVAL)
            ready = self._ready()
        if ready is None:
            raise CLO3DConnectionError(
                f"No protocol-{PROTOCOL} CLO bridge ready at {self.comm_dir}. "
                "Start the updated bridge in CLO with the same CLO3D_MCP_DIR."
            )
        request_id = uuid.uuid4().hex
        directory = Path(self.comm_dir)
        request_path = directory / "requests" / (request_id + ".json")
        response_path = directory / "responses" / (request_id + ".json")
        request = {
            "protocol": PROTOCOL, "session": ready["session"], "id": request_id,
            "type": command_type, "params": params if params is not None else {},
            "expires_at": time.time() + max(0, deadline - time.monotonic()),
        }
        try:
            atomic_json(request_path, request)
            while True:
                response = read_json(response_path)
                if isinstance(response, dict) and response.get("id") == request_id:
                    if response.get("status") == "error":
                        raise CLO3DConnectionError("CLO3D error: " + str(response.get("message")))
                    if response.get("status") != "success":
                        raise CLO3DConnectionError("Invalid CLO3D response status; command was not retried")
                    return response.get("result", {})
                if self._ready() != ready:
                    # A graceful stop may publish its response just after our first read.
                    if response_path.exists():
                        continue
                    raise CLO3DConnectionError(
                        "CLO bridge stopped or restarted. Command outcome is unknown; it was not retried."
                    )
                if time.monotonic() >= deadline:
                    raise CLO3DConnectionError(
                        f"Timed out waiting for CLO3D ({timeout}s). The command may still be running; "
                        "it was not retried. Inspect CLO before repeating a mutation."
                    )
                time.sleep(POLL_INTERVAL)
        except OSError as exc:
            raise CLO3DConnectionError(
                f"CLO3D communication failed: {exc}. Command was not retried; check its outcome."
            ) from exc
        finally:
            # Only cancel our own unclaimed request. A running call cannot be cancelled.
            request_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)

    def ping(self):
        try:
            return self.send_command("ping").get("pong", False)
        except CLO3DConnectionError:
            return False


_connection = None


def get_connection(comm_dir=None):
    global _connection
    if _connection is None or (comm_dir is not None and str(comm_dir) != _connection.comm_dir):
        _connection = CLO3DConnection(comm_dir)
    return _connection
