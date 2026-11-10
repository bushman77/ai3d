"""Small, project-independent front end for AI3D pipelines and asset inspection."""

import argparse
import json
from pathlib import Path
import sys

from ai3d.export.validation import readable_glb


def main(argv: list[str] | None = None) -> int:
    """Dispatch CLI commands without importing heavyweight inference dependencies."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = argparse.ArgumentParser(
        prog="ai3d",
        description="AI3D: generate, inspect and validate local 3D assets",
    )
    root.add_argument(
        "command", nargs="?", choices=("generate", "inspect"),
        help="generate an asset, or inspect an existing GLB",
    )
    if not args or args[0] in ("-h", "--help"):
        root.print_help()
        return 0

    if args[0] == "generate":
        from pipelines.image_to_3d import main as generate

        generate(args[1:], prog="ai3d generate")
        return 0

    if args[0] == "inspect":
        parser = argparse.ArgumentParser(
            prog="ai3d inspect",
            description="Inspect a binary glTF 2.0 (.glb) file without Blender",
        )
        parser.add_argument("file", type=Path, help="Existing GLB asset")
        parser.add_argument(
            "--require-texture", action="store_true",
            help="Require UVs, base-color texture reference and an image",
        )
        options = parser.parse_args(args[1:])
        result = readable_glb(options.file.expanduser().resolve(), options.require_texture)
        print(json.dumps(result, indent=2))
        return 0

    root.parse_args(args)
    return 2
