"""Compatibility entry point for the extracted AI3D static-GLB optimizer.

Preserves the existing Blender --python script path and command-line flags.
All Blender optimization logic now lives in ai3d/optimization/blender_finalize.py.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    implementation = (
        Path(__file__).resolve().parent.parent
        / "ai3d" / "optimization" / "blender_finalize.py"
    )
    runpy.run_path(str(implementation), run_name="__main__")
