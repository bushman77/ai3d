"""Pure Paint3D texture-stage command builder.

The controlling Python interpreter does not import Paint3D or CUDA.
"""

from pathlib import Path


def build_texture_command(
    python: Path, mesh: Path, reference: Path, output: Path,
    *, quality: str = "fast", category: str = "humanoid",
    max_views: int = 2, view_resolution: int = 256,
    render_size: int = 512, texture_size: int = 1024,
    bake_exp: int = 6,
) -> list[str]:
    """Return the original Paint3D texture CLI arguments."""
    if any(v < 1 for v in (max_views, view_resolution, render_size, texture_size, bake_exp)):
        raise ValueError("Paint3D numeric settings must be positive")
    if category not in ("humanoid", "prop", "weapon", "none"):
        raise ValueError(f"Unsupported Paint3D category: {category}")
    if quality not in ("fast", "low", "medium", "high", "highest"):
        raise ValueError(f"Unsupported Paint3D quality: {quality}")
    command = [
        str(python), "-m", "paint3d", "texture", str(mesh),
        "-i", str(reference), "-o", str(output), "--quality", quality,
        "--max-views", str(max_views), "--view-resolution", str(view_resolution),
        "--render-size", str(render_size), "--texture-size", str(texture_size),
        "--bake-exp", str(bake_exp), "--no-vramd", "--profile",
    ]
    if category != "none":
        command += ["--category", category]
    return command
