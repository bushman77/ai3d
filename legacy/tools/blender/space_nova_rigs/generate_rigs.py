"""Headless command-line entry point for the Space Nova rig generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
sys.dont_write_bytecode = True

from generator import export_template, load_overrides, template_with_overrides


def blender_arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_arguments() -> argparse.Namespace:
    default_output = SCRIPT_DIRECTORY / "output"
    parser = argparse.ArgumentParser(description="Generate standalone Space Nova humanoid rigs")
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--rig", choices=("male", "female", "both"), default="both")
    parser.add_argument("--male-config", type=Path, help="partial JSON proportion overrides")
    parser.add_argument("--female-config", type=Path, help="partial JSON proportion overrides")
    return parser.parse_args(blender_arguments())


def main() -> None:
    arguments = parse_arguments()
    selected = ("male", "female") if arguments.rig == "both" else (arguments.rig,)
    override_paths = {"male": arguments.male_config, "female": arguments.female_config}

    for key in selected:
        template = template_with_overrides(key, load_overrides(override_paths[key]))
        assets = export_template(template, arguments.output_dir)
        print(
            f"SPACE_NOVA_GENERATED {template.rig_name} "
            f"blend={assets['blend']} glb={assets['glb']}"
        )


if __name__ == "__main__":
    main()

