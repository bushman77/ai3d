"""Host-side command builders for the scripts in ai3d/blender (no bpy import)."""
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def blender_command(blender: str, script: str, args: list[str]) -> list[str]:
    path = SCRIPTS / script
    if not path.is_file():
        raise ValueError(f"Unknown Blender script: {script}")
    return [str(blender), "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(path), "--", *[str(a) for a in args]]
