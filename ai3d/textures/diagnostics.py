"""Optional Paint3D debug capture; disabled by default.

The upstream Paint3D revision used by AI3D supports PAINT3D_DEBUG_DIR.
When enabled, it saves the selected camera views and the UV texture at
several points during baking. No model is invoked by these helpers.
"""

from pathlib import Path
from typing import Mapping


DEBUG_FILES = ("ref.png", "tex_baked.png", "tex_trust.png", "tex_inpainted.png")


def debug_directory(run_dir: Path) -> Path:
    """Locate per-run diagnostic output without creating files."""
    return Path(run_dir) / "paint_debug"


def paint_debug_environment(
    env: Mapping[str, str], run_dir: Path, *, enabled: bool = False
) -> dict[str, str]:
    """Copy a subprocess environment and opt into Paint3D debug capture.

    With debugging off, inherited PAINT3D_DEBUG_DIR is removed to keep
    generated files within this run's explicitly selected output root.
    """
    result = dict(env)
    result.pop("PAINT3D_DEBUG_DIR", None)
    if enabled:
        result["PAINT3D_DEBUG_DIR"] = str(debug_directory(run_dir))
    return result


def expected_debug_images(run_dir: Path) -> list[Path]:
    """Key files expected when the pinned Paint3D debug hook is enabled."""
    return [debug_directory(run_dir) / file for file in DEBUG_FILES]
