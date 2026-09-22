"""Artifact and API-result checks shared by the live harness and offline tests."""
import json
from pathlib import Path
import struct
from urllib.parse import unquote
import zipfile

from clo3d_mcp.contracts import FAILURE_FLAGS


def validate_result(tool, payload, arguments):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object result")
    for flag in FAILURE_FLAGS:
        if payload.get(flag) is False:
            raise ValueError(f"{flag}=false")
    if not (tool.startswith("export_") or tool == "save_project"):
        return
    paths = payload.get("file_paths", payload.get("file_path", []))
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        raise ValueError("No output paths returned")
    for name in paths:
        path = Path(name)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty artifact: {path}")
        suffix = path.suffix.lower()
        if suffix == ".obj":
            lines = path.read_text().splitlines()
            if not any(s.startswith("v ") for s in lines) or not any(s.startswith("f ") for s in lines):
                raise ValueError("OBJ has no geometry")
        elif suffix == ".fbx":
            with path.open("rb") as stream:
                if not stream.read(24).startswith(b"Kaydara FBX Binary"):
                    raise ValueError("Invalid binary FBX header")
        elif suffix == ".glb":
            data = path.read_bytes()
            magic, version, size = struct.unpack_from("<4sII", data)
            length, kind = struct.unpack_from("<II", data, 12)
            if magic != b"glTF" or version != 2 or size != len(data) or kind != 0x4E4F534A:
                raise ValueError("Invalid GLB header or length")
            if not json.loads(data[20:20 + length]).get("meshes"):
                raise ValueError("GLB has no meshes")
        elif suffix == ".gltf":
            data = json.loads(path.read_text())
            if data.get("asset", {}).get("version") != "2.0" or not data.get("meshes"):
                raise ValueError("Invalid glTF or no meshes")
            for item in data.get("buffers", []) + data.get("images", []):
                uri = item.get("uri", "")
                if uri and not uri.startswith("data:") and not (path.parent / unquote(uri)).is_file():
                    raise ValueError(f"Missing glTF resource: {uri}")
        elif suffix == ".json":
            if not json.loads(path.read_text()):
                raise ValueError("Empty JSON artifact")
        elif suffix in {".zprj", ".zpac"}:
            with zipfile.ZipFile(path) as archive:
                if not archive.namelist() or archive.testzip():
                    raise ValueError("Invalid CLO archive")
        elif suffix == ".png":
            with path.open("rb") as stream:
                header = stream.read(24)
            if not header.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid PNG header")
            width, height = struct.unpack_from(">II", header, 16)
            if width == 0 or height == 0:
                raise ValueError("Empty image dimensions")
            if tool == "export_turntable" and (width, height) != (arguments["width"], arguments["height"]):
                raise ValueError("Turntable dimensions differ from request")
    if tool == "export_turntable" and len(paths) != arguments["number_of_images"]:
        raise ValueError("Turntable image count differs from request")
