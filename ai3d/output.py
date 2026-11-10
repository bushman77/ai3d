"""Generated-output directory policy for project-independent AI3D runs.

All generated files for a named run live beneath a single configurable root.
The default is <repository>/outputs, not ~/ai3d/pipeline_runs or assets/.
Existing runs in other directories are never moved automatically.
"""

from pathlib import Path
import re

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "outputs"


def run_directory(asset_name: str, output_root: Path | None = None) -> Path:
    """Resolve a self-contained asset run folder without creating it.

    Rejects traversal and special directory names. The caller decides when
    to create the directory so dry runs can remain read-only.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", asset_name):
        raise RuntimeError("--name must contain letters, numbers, hyphens, underscores only")
    root = Path(output_root) if output_root is not None else DEFAULT_OUTPUT_ROOT
    return root.expanduser().resolve() / asset_name
