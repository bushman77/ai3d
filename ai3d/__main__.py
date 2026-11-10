"""Run the standalone AI3D command-line interface with python -m ai3d."""

import subprocess
import sys

from .cli import main


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
