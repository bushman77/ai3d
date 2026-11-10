#!/usr/bin/env python3
"""Backward-compatible entry point for the original Space Nova pipeline.

Project-neutral orchestration now resides in pipelines.image_to_3d.
Keep this path and public argument helpers available for existing scripts.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.image_to_3d import STAGES, arguments, main, positive, should_stop  # noqa: E402


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
