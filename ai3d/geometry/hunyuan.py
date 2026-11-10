"""Pure command builders for Hunyuan shape and prepaint mesh processing."""

from pathlib import Path


def build_shape_command(
    python: Path, script: Path, reference: Path, output: Path, *, steps: int = 20
) -> list[str]:
    """Build the external first_mesh.py shape inference command."""
    if steps < 1:
        raise ValueError("steps must be positive")
    return [
        str(python), str(script), "--input", str(reference),
        "--output", str(output), "--steps", str(steps),
    ]


def build_prepaint_command(
    blender: str, script: Path, input_mesh: Path, output: Path,
    *, target_faces: int = 40000,
) -> list[str]:
    """Build the upstream geometry-only Blender optimizer command."""
    if target_faces < 1:
        raise ValueError("target_faces must be positive")
    return [
        str(blender), "--background", "--factory-startup",
        "--python-exit-code", "1", "--python", str(script),
        "--", "--input", str(input_mesh), "--target-faces",
        str(target_faces), "--output", str(output),
    ]
