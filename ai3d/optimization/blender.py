"""Project-independent command construction for Blender-based GLB optimization.

No Blender Python module is imported by this file. The returned command
runs the dedicated Blender script in a separate Blender process.
"""

from pathlib import Path


def build_finalize_command(
    blender: str,
    script: Path,
    input_mesh: Path,
    output_mesh: Path,
    target_faces: int = 15000,
) -> list[str]:
    """Build the original static-mesh optimization command.

    The historical CLI flag is `--target-faces`, but the implementation
    targets a triangle count. This function does not execute the command.
    """
    source = Path(input_mesh)
    output = Path(output_mesh)
    if source.suffix.lower() != ".glb" or output.suffix.lower() != ".glb":
        raise ValueError("Input and output must be GLB files")
    if source.expanduser().resolve() == output.expanduser().resolve():
        raise ValueError("Output must be distinct from input")
    if target_faces < 100:
        raise ValueError("target_faces must be >= 100")
    return [
        str(blender), "--background", "--factory-startup",
        "--python-exit-code", "1", "--python", str(script),
        "--", "--input", str(source), "--output", str(output),
        "--target-faces", str(target_faces),
    ]
