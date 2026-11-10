"""CLI for creating and validating project-independent character cards."""

import argparse
from pathlib import Path

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
    else:
        definition = load_card(args.file)
        print(f"VALID: {definition['id']} — {definition['name']} ({len(definition['parts'])} parts)")
        print("Parts: " + ", ".join(part["id"] for part in definition["parts"]))
    return 0
