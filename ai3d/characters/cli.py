"""CLI for creating and validating project-independent character cards."""

import argparse
from pathlib import Path
import subprocess
import sys

from ai3d.image.qwen import DEFAULT_SD_CLI, DEFAULT_MODEL_DIR
from ai3d.output import DEFAULT_OUTPUT_ROOT

from .card import DEFAULT_CARDS_DIR, load_card, new_card, save_new_card


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai3d character",
        description="Create and validate reusable character cards (no GPU needed)",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create a card from the permanent template")
    init.add_argument("id", help="Lowercase snake_case character ID")
    init.add_argument("--name", help="Display name")
    init.add_argument("--category", default="humanoid", help="Character category/species")
    init.add_argument("--output", type=Path, help="Output JSON card path")
    validate = sub.add_parser("validate", help="Check a saved card")
    validate.add_argument("file", type=Path, help="Card JSON file")
    reference = sub.add_parser(
        "reference", help="Generate a character-part reference with Qwen"
    )
    reference.add_argument("card", type=Path, help="Existing character card JSON")
    reference.add_argument("--part", required=True, help="Part ID within the card")
    reference.add_argument("--view", help="Override part.reference_view")
    reference.add_argument("--name", help="Output run name (default: character_part_view)")
    reference.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    reference.add_argument("--sd-cli", type=Path, default=DEFAULT_SD_CLI)
    reference.add_argument("--qwen-model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    reference.add_argument("--width", type=int, default=384)
    reference.add_argument("--height", type=int, default=384)
    reference.add_argument("--steps", type=int, default=12)
    reference.add_argument("--ram", default="10G", help="Qwen systemd MemoryMax")
    reference.add_argument("--swap", default="1G", help="Qwen systemd MemorySwapMax")
    reference.add_argument("--dry-run", action="store_true", help="Print prompt and command, no GPU")
    reference.add_argument("--resume", action="store_true", help="Reuse matching existing image")
    reference.add_argument("--force", action="store_true", help="Explicitly overwrite existing image")

    args = parser.parse_args(argv)

    if args.action == "init":
        try:
            definition = new_card(args.id, args.name, args.category)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        path = args.output if args.output is not None else DEFAULT_CARDS_DIR / f"{definition['id']}.json"
        try:
            save_new_card(definition, path)
        except FileExistsError as exc:
            raise RuntimeError(f"Card already exists; refusing overwrite: {path}") from exc
        print(f"Created character card: {path}")
        print("Edit identity, appearance, prompts, references and parts, then validate.")
    elif args.action == "validate":
        definition = load_card(args.file)
        print(f"VALID: {definition['id']} — {definition['name']} ({len(definition['parts'])} parts)")
        print("Parts: " + ", ".join(part["id"] for part in definition["parts"]))
    elif args.action == "reference":
        from .reference import run_reference

        try:
            definition = load_card(args.card)
            run_reference(
                definition, args.card,
                part_id=args.part, view=args.view, name=args.name,
                output_dir=args.output_dir,
                sd_cli=args.sd_cli, model_dir=args.qwen_model_dir,
                width=args.width, height=args.height, steps=args.steps,
                ram_limit=args.ram, swap_limit=args.swap,
                dry_run=args.dry_run, resume=args.resume, force=args.force,
            )
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 0
