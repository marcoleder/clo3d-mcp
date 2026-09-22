"""
CLO3D MCP Server: FastMCP server exposing CLO3D tools to LLMs.

Bridges Codex/Claude/Cursor and CLO3D via the Model Context Protocol.
Communicates with the CLO3D plugin through a shared file directory.
"""

from mcp.server.fastmcp import FastMCP
from clo3d_mcp.connection import get_connection, CLO3DConnectionError

mcp = FastMCP(
    "clo3d",
    instructions="Control CLO3D — the industry-standard 3D garment design software. "
    "Create patterns, manage fabrics, run simulations, export 3D models, and more.",
)


def _send(command: str, params: dict | None = None) -> dict:
    """Send a command to CLO3D and return the result."""
    conn = get_connection()
    return conn.send_command(command, params)


# ─── Scene Tools ───────────────────────────────────────────────────────────


@mcp.tool()
def get_project_info() -> dict:
    """Get information about the current CLO3D project including name, path, version, and counts for patterns, fabrics, and colorways."""
    return _send("get_project_info")


@mcp.tool()
def new_project() -> dict:
    """Create a new empty CLO3D project, clearing the current scene."""
    return _send("new_project")


@mcp.tool()
def open_file(file_path: str) -> dict:
    """Open a file in CLO3D. Supports .zprj, .zpac, .avt, .obj, .fbx formats.

    A .zprj open verifies the active project path. An already active path is
    an explicit no-op (already_active=True), preserving unsaved edits. Avatar
    and fabric files use dedicated import handlers. An unverifiable import
    blocks further mutations until a distinct .zprj backup is opened; do not retry.

    Args:
        file_path: Absolute path to the file to open.
    """
    return _send("open_file", {"file_path": file_path})


@mcp.tool()
def save_project(file_path: str) -> dict:
    """Save the current CLO3D project as a .zprj file.

    Args:
        file_path: Absolute path for the saved .zprj file.
    """
    return _send("save_file", {"file_path": file_path})


@mcp.tool()
def get_garment_info() -> dict:
    """Export and retrieve garment metadata as JSON, including pattern details, fabric assignments, and measurements."""
    return _send("get_garment_info")


# ─── Pattern Tools ─────────────────────────────────────────────────────────


@mcp.tool()
def get_pattern_count() -> dict:
    """Get the total number of pattern pieces in the current project."""
    return _send("get_pattern_count")


@mcp.tool()
def get_pattern_list() -> dict:
    """Get a list of all pattern pieces with their indices and names."""
    return _send("get_pattern_list")


@mcp.tool()
def get_pattern_info(pattern_index: int) -> dict:
    """Get detailed information about a specific pattern piece.

    Args:
        pattern_index: Zero-based index of the pattern piece.
    """
    return _send("get_pattern_info", {"pattern_index": pattern_index})


@mcp.tool()
def get_pattern_bounding_box(pattern_index: int) -> dict:
    """Get the bounding box (width/height) of a pattern piece.

    Args:
        pattern_index: Zero-based index of the pattern piece.
    """
    return _send("get_bounding_box", {"pattern_index": pattern_index})


@mcp.tool()
def set_pattern_name(pattern_index: int, name: str) -> dict:
    """Rename a pattern piece.

    Args:
        pattern_index: Zero-based index of the pattern piece.
        name: New name for the pattern piece.
    """
    return _send("set_pattern_name", {"pattern_index": pattern_index, "name": name})


@mcp.tool()
def copy_pattern(pattern_index: int, x: float = 0, y: float = 0) -> dict:
    """Duplicate a pattern piece at a given position.

    Args:
        pattern_index: Zero-based index of the pattern piece to copy.
        x: X position offset for the copy (mm).
        y: Y position offset for the copy (mm).
    """
    return _send("copy_pattern", {"pattern_index": pattern_index, "x": x, "y": y})


@mcp.tool()
def delete_pattern(pattern_index: int) -> dict:
    """Delete a pattern piece from the project.

    Args:
        pattern_index: Zero-based index of the pattern piece to delete.
    """
    return _send("delete_pattern", {"pattern_index": pattern_index})


@mcp.tool()
def flip_pattern(
    pattern_index: int, horizontal: bool = True, each: bool = True
) -> dict:
    """Flip a pattern piece horizontally or vertically.

    Args:
        pattern_index: Zero-based index of the pattern piece to flip.
        horizontal: True for horizontal flip, False for vertical flip.
        each: True flips each piece about its own axis; False flips the
            selection as a group.
    """
    return _send(
        "flip_pattern",
        {"pattern_index": pattern_index, "horizontal": horizontal, "each": each},
    )


@mcp.tool()
def create_pattern(points: list[list[float]]) -> dict:
    """Create a new pattern piece from vertex points.

    Args:
        points: List of [x, y] or [x, y, type] coordinates in mm.
                Type: 0=straight (default), 2=spline, 3=bezier.
                Example: [[0,0], [100,0], [100,200], [0,200]]
    """
    return _send("create_pattern", {"points": points})


@mcp.tool()
def get_arrangement_list() -> dict:
    """Get the list of arrangement points on the avatar."""
    return _send("get_arrangement_list")


# ─── Fabric Tools ──────────────────────────────────────────────────────────


@mcp.tool()
def get_fabric_list() -> dict:
    """Get all fabrics, including unused fabrics, with their indices and names."""
    return _send("get_fabric_list")


@mcp.tool()
def add_fabric(file_path: str) -> dict:
    """Add a new fabric to the project from a .zfab or .jfab file.

    Args:
        file_path: Absolute path to the fabric file (.zfab or .jfab).
    """
    return _send("add_fabric", {"file_path": file_path})


@mcp.tool()
def replace_fabric(fabric_index: int, file_path: str) -> dict:
    """Replace an existing fabric with a new one from file.

    Args:
        fabric_index: Zero-based index of the fabric to replace.
        file_path: Absolute path to the replacement fabric file (.zfab).
    """
    return _send("replace_fabric", {"fabric_index": fabric_index, "file_path": file_path})


@mcp.tool()
def assign_fabric_to_pattern(
    fabric_index: int, pattern_index: int, assign_option: int = 1
) -> dict:
    """Assign a fabric to a pattern piece.

    Args:
        fabric_index: Zero-based index of the fabric.
        pattern_index: Zero-based index of the pattern piece.
        assign_option: 1=current colorway only, 2=all colorways (unlinked), 3=all colorways (linked).
    """
    return _send(
        "assign_fabric",
        {
            "fabric_index": fabric_index,
            "pattern_index": pattern_index,
            "assign_option": assign_option,
        },
    )


@mcp.tool()
def set_fabric_color(
    fabric_index: int,
    r: int = 255,
    g: int = 255,
    b: int = 255,
    a: int = 255,
    material_face: int = 0,
) -> dict:
    """Set the PBR base color of a fabric.

    Args:
        fabric_index: Zero-based index of the fabric.
        r: Red channel (0-255).
        g: Green channel (0-255).
        b: Blue channel (0-255).
        a: Alpha channel (0-255).
        material_face: Which face to colour — 0 = front, 1 = back, 2 = side.
    """
    return _send(
        "set_fabric_color",
        {
            "fabric_index": fabric_index,
            "r": r, "g": g, "b": b, "a": a,
            "material_face": material_face,
        },
    )


@mcp.tool()
def get_fabric_for_pattern(pattern_index: int) -> dict:
    """Get which fabric is assigned to a pattern piece.

    Args:
        pattern_index: Zero-based index of the pattern piece.
    """
    return _send("get_fabric_for_pattern", {"pattern_index": pattern_index})


# ─── Export Tools ──────────────────────────────────────────────────────────


@mcp.tool()
def export_obj(file_path: str, options: dict | None = None) -> dict:
    """Export the garment as an OBJ file.

    Args:
        file_path: Absolute path for the exported .obj file.
        options: Optional export options (bExportGarment, bExportAvatar, bThin, scale, etc.).

    Options require the native shim or a constructible Python option type.
    Without options, the Python overload may open an export dialog.
    """
    params = {"file_path": file_path}
    if options:
        params["options"] = options
    return _send("export_obj", params)


@mcp.tool()
def export_fbx(file_path: str, options: dict | None = None) -> dict:
    """Export the garment as an FBX file.

    Args:
        file_path: Absolute path for the exported .fbx file.
        options: Optional export options (bExportGarment, bExportAvatar, scale, etc.).

    CLO 2026.1 requires the native shim for this export.
    """
    params = {"file_path": file_path}
    if options:
        params["options"] = options
    return _send("export_fbx", params)


@mcp.tool()
def export_glb(file_path: str, options: dict | None = None) -> dict:
    """Export the garment as a GLB (binary glTF) file.

    Args:
        file_path: Absolute path for the exported .glb file.
        options: Optional export options.
    """
    params = {"file_path": file_path}
    if options:
        params["options"] = options
    # Without the shim, dialog fallback is available only without options.
    return _send("export_glb", params)


@mcp.tool()
def export_gltf(file_path: str, options: dict | None = None) -> dict:
    """Export the garment as a glTF file.

    Args:
        file_path: Absolute path for the exported .gltf file.
        options: Optional export options.
    """
    params = {"file_path": file_path}
    if options:
        params["options"] = options
    # Without the shim, dialog fallback is available only without options.
    return _send("export_gltf", params)


@mcp.tool()
def export_thumbnail(file_path: str) -> dict:
    """Export a 3D viewport thumbnail.

    Args:
        file_path: Absolute path for the exported image file.

    Note: CLO's ExportThumbnail3D takes no size arguments — the thumbnail
    dimensions are fixed by the application.
    """
    return _send("export_thumbnail", {"file_path": file_path})


@mcp.tool()
def export_snapshot(file_path: str) -> dict:
    """Export multi-view snapshot images of the 3D garment.

    Returns file_paths as a flat list of verified, nonempty files. The legacy
    file_path key preserves CLO's original result (string or nested path list).

    Args:
        file_path: Absolute path (directory or base name) for snapshot images.
    """
    return _send("export_snapshot", {"file_path": file_path})


@mcp.tool()
def export_turntable(
    file_path: str,
    number_of_images: int = 36,
    width: int = 2500,
    height: int = 2500,
) -> dict:
    """Export a 360-degree turntable image sequence.

    Args:
        file_path: Absolute image filename, such as /output/view.png.
            Uses the current colorway to work around the broken ordinary path overload.
        number_of_images: How many frames to render around the turn.
        width: Frame width in pixels.
        height: Frame height in pixels.
    """
    return _send(
        "export_turntable",
        {
            "file_path": file_path,
            "number_of_images": number_of_images,
            "width": width,
            "height": height,
        },
    )


@mcp.tool()
def export_tech_pack(file_path: str, options: dict | None = None) -> dict:
    """Export a tech pack with JSON metadata and images.

    Args:
        file_path: Absolute .json filename; sidecar files are written alongside it.
            Default m_bSaveZprj/m_bSaveZpac flags can change the active project path.
        options: Optional flags — m_bSaveZprj, m_bSaveZpac, m_bExportTextures,
            m_bCaptureItemThumbnail, m_bShowModalProgressBar, m_bUseAverageColor.
    """
    params = {"file_path": file_path}
    if options:
        params["options"] = options
    return _send("export_tech_pack", params)


# ─── Import Tools ──────────────────────────────────────────────────────────


@mcp.tool()
def import_file(file_path: str) -> dict:
    """Import a file into CLO3D. Auto-detects type from extension (.zprj, .zpac, .obj, .fbx, .avt, etc.).

    Uses the same verification and already-active no-op behavior as open_file.
    Nonproject imports must change observable scene state; uncertain outcomes
    block further mutations. AVT requires native shim ABI 2; there is no generic
    ImportFile fallback because it can replace the garment.

    Args:
        file_path: Absolute path to the file to import.
    """
    return _send("import_file", {"file_path": file_path})


# ─── Simulation Tools ─────────────────────────────────────────────────────


@mcp.tool()
def simulate(steps: int = 100) -> dict:
    """Run cloth simulation for a number of steps.

    Args:
        steps: Number of simulation steps to run (default 100).
    """
    return _send("simulate", {"steps": steps})


# ─── Colorway Tools ───────────────────────────────────────────────────────


@mcp.tool()
def get_colorways() -> dict:
    """Get a list of all colorways in the current project with names and which is active."""
    return _send("get_colorways")


@mcp.tool()
def set_current_colorway(colorway_index: int) -> dict:
    """Switch to a different colorway.

    Args:
        colorway_index: Zero-based index of the colorway to activate.
    """
    return _send("set_current_colorway", {"colorway_index": colorway_index})


@mcp.tool()
def set_colorway_name(colorway_index: int, name: str) -> dict:
    """Rename a colorway.

    Args:
        colorway_index: Zero-based index of the colorway to rename.
        name: New name for the colorway.
    """
    return _send("set_colorway_name", {"colorway_index": colorway_index, "name": name})


@mcp.tool()
def copy_colorway(colorway_index: int, copy_option: int = 0) -> dict:
    """Duplicate a colorway, returning the new colorway's index.

    Args:
        colorway_index: Zero-based index of the colorway to copy.
        copy_option: 0 = unlink all properties, 1 = unlink material properties
            only, 2 = link all properties to the source colorway.
    """
    return _send(
        "copy_colorway",
        {"colorway_index": colorway_index, "copy_option": copy_option},
    )


@mcp.tool()
def delete_colorway(colorway_index: int) -> dict:
    """Delete a colorway from the project.

    Args:
        colorway_index: Zero-based index of the colorway to delete.
    """
    return _send("delete_colorway", {"colorway_index": colorway_index})


# ─── Avatar Tools ─────────────────────────────────────────────────────────


@mcp.tool()
def get_avatars() -> dict:
    """List the avatars in the current project, with names and genders."""
    return _send("get_avatars")


@mcp.tool()
def get_avatar_genders() -> dict:
    """Get the gender of each avatar in the current project."""
    return _send("get_avatar_genders")


@mcp.tool()
def show_hide_avatar(show: bool = True) -> dict:
    """Show or hide the avatar in the 3D viewport.

    Args:
        show: True to show the avatar, False to hide it.
    """
    return _send("show_hide_avatar", {"show": show})


@mcp.tool()
def import_avatar(file_path: str, apf_path: str = "") -> dict:
    """Import an avatar into the current project.

    Verifies avatar count growth and unchanged garment names/count and project
    path. A failed postcondition may leave an added avatar: it is not rolled
    back. Further mutations are blocked until a distinct .zprj backup is loaded.

    Args:
        file_path: Absolute path to the avatar file (.avt or .avac).
        apf_path: Optional pose (.apf), supported only with .avac.
            .avt requires native shim ABI 2 and adds the avatar without replacing the garment.
    """
    return _send("import_avatar", {"file_path": file_path, "apf_path": apf_path})


# ─── Additional Fabric Tools ──────────────────────────────────────────────


@mcp.tool()
def get_fabric_count() -> dict:
    """Get the total number of fabrics, including unused fabrics, in the current project."""
    return _send("get_fabric_count")


@mcp.tool()
def import_fabric(file_path: str) -> dict:
    """Import a fabric from file, returning its new fabric index.

    Args:
        file_path: Absolute path to the fabric file (.zfab).
    """
    return _send("import_fabric", {"file_path": file_path})


@mcp.tool()
def delete_fabric(fabric_index: int) -> dict:
    """Delete a fabric from the project.

    Args:
        fabric_index: Zero-based index of the fabric to delete.
    """
    return _send("delete_fabric", {"fabric_index": fabric_index})


# ─── Additional Simulation Tools ──────────────────────────────────────────


@mcp.tool()
def set_simulation_quality(quality: int, simulation_mode: int = 0) -> dict:
    """Set the simulation quality preset.

    Args:
        quality: 0 = Normal (default), 1 = Animation (stable),
            2 = Fitting (accurate fabric), 3 = FAST (GPU).
        simulation_mode: 0 = CPU, 1 = FAST (GPU).
    """
    return _send(
        "set_simulation_quality",
        {"quality": quality, "simulation_mode": simulation_mode},
    )


# ─── Connection Tools ─────────────────────────────────────────────────────


@mcp.tool()
def ping() -> dict:
    """Check that the CLO3D bridge plugin is running and reachable.

    Use this first when other tools time out — it confirms whether the plugin
    script is actually running inside CLO3D.
    """
    return _send("ping")


@mcp.tool()
def refresh_view() -> dict:
    """Force the 3D viewport to redraw.

    Useful after a batch of changes so the garment on screen reflects them.
    """
    return _send("refresh_view")


@mcp.tool()
def set_live_preview(enabled: bool = True, path: str | None = None) -> dict:
    """Turn live preview on or off.

    When on, CLO's 3D viewport is redrawn after every state-changing command,
    so a batch can be watched as it happens rather than only at the end.

    Costs roughly 0.3-0.5s and a ~1 MB PNG per command, so leave it off for
    long unattended batches.

    Args:
        enabled: True to redraw after each change, False to stop.
        path: Optional path for the snapshot PNG used to force the redraw.
    """
    params: dict = {"enabled": enabled}
    if path:
        params["path"] = path
    return _send("set_live_preview", params)


@mcp.tool()
def stop_bridge() -> dict:
    """Release CLO's UI by stopping the shared bridge after current work.

    Affects all connected clients. Restart the bridge in CLO before using more
    tools. Cannot interrupt an in-progress native call or a modal dialog.
    """
    return _send("stop_bridge")
