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

    generate = sub.add_parser(
        "generate", help="Generate every selected character part sequentially"
    )
    generate.add_argument("card", type=Path, help="Existing character card JSON")
    selection = generate.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="Process every part")
    selection.add_argument("--part", action="append", dest="parts", help="Part ID; repeat for multiple")
    generate.add_argument("--skip", action="append", default=[], help="Skip a part, e.g. an already approved head")
    generate.add_argument("--include-regions", action="store_true",
                          help="Also reconstruct region parts as experimental standalone meshes")
    generate.add_argument("--stop-after", choices=("reference", "shape", "paint", "game"),
                          default="reference", help="Maximum stage to run (default: reference only)")
    generate.add_argument("--run-prefix", help="Name prefix for independently saved output runs")
    generate.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    generate.add_argument("--sd-cli", type=Path, default=DEFAULT_SD_CLI)
    generate.add_argument("--qwen-model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    generate.add_argument("--hunyuan", type=Path)
    generate.add_argument("--aigamekit", type=Path)
    generate.add_argument("--blender", default="blender")
    generate.add_argument("--qwen-width", type=int, default=384)
    generate.add_argument("--qwen-height", type=int, default=384)
    generate.add_argument("--qwen-steps", type=int, default=12)
    generate.add_argument("--qwen-ram", default="10G")
    generate.add_argument("--qwen-swap", default="1G")
    generate.add_argument("--shape-steps", type=int, default=20)
    generate.add_argument("--paint-faces", type=int, default=40000)
    generate.add_argument("--game-faces", type=int, default=15000)
    generate.add_argument("--view-resolution", type=int, default=256)
    generate.add_argument("--texture-size", type=int, default=1024)
    generate.add_argument("--render-size", type=int, default=512)
    generate.add_argument("--quality", choices=("fast", "low", "medium", "high", "highest"), default="fast")
    generate.add_argument("--max-views", type=int, default=2)
    generate.add_argument("--paint-debug", action="store_true")
    action = generate.add_mutually_exclusive_group()
    action.add_argument("--resume", action="store_true", help="Reuse unchanged outputs and continue interrupted runs")
    action.add_argument("--force", action="store_true", help="Explicitly rebuild and overwrite matching run outputs")
    generate.add_argument("--dry-run", action="store_true", help="Plan only; do not launch Qwen or write files")

    assembly = sub.add_parser(
        "assemble", help="Build an editable two-part Blender comparison preview"
    )
    assembly.add_argument("card", type=Path, help="Character card JSON")
    assembly.add_argument("--run-prefix", required=True,
                          help="Prefix used for the existing component GLB output folders")
    assembly.add_argument("--name", required=True,
                          help="New output folder name inside outputs/")
    assembly.add_argument("--base", default="body", help="Base part ID (default: body)")
    assembly.add_argument("--attach", default="head", help="Part to compare (default: head)")
    assembly.add_argument("--source-stage", choices=("painted", "game"),
                          default="painted", help="Use higher-detail 05_painted.glb by default")
    assembly.add_argument("--layout", choices=("side_by_side", "overlay"),
                          default="side_by_side", help="Side-by-side preview or overlapping origins")
    assembly.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    assembly.add_argument("--blender", default="blender")
    assembly.add_argument("--dry-run", action="store_true",
                          help="Show source paths and layout without writing or launching Blender")
    assembly.add_argument("--rebuild", action="store_true",
                          help="Reuse edited assembly.json and explicitly regenerate preview files")

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
    elif args.action == "generate":
        from .batch import generate_character

        try:
            definition = load_card(args.card)
            generate_character(
                definition, args.card,
                all_parts=args.all, part_ids=args.parts, skip=args.skip,
                include_regions=args.include_regions, stop_after=args.stop_after,
                run_prefix=args.run_prefix, output_dir=args.output_dir,
                sd_cli=args.sd_cli, qwen_model_dir=args.qwen_model_dir,
                hunyuan=args.hunyuan, aigamekit=args.aigamekit, blender=args.blender,
                qwen_width=args.qwen_width, qwen_height=args.qwen_height,
                qwen_steps=args.qwen_steps, qwen_ram=args.qwen_ram,
                qwen_swap=args.qwen_swap, shape_steps=args.shape_steps,
                paint_faces=args.paint_faces, game_faces=args.game_faces,
                view_resolution=args.view_resolution, texture_size=args.texture_size,
                render_size=args.render_size, quality=args.quality,
                max_views=args.max_views, paint_debug=args.paint_debug,
                resume=args.resume, force=args.force, dry_run=args.dry_run,
            )
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.action == "assemble":
        from .assembly import assemble_preview

        try:
            assemble_preview(
                args.card, name=args.name, run_prefix=args.run_prefix,
                base=args.base, attach=args.attach,
                source_stage=args.source_stage, layout=args.layout,
                output_root=args.output_dir, blender=args.blender,
                dry_run=args.dry_run, rebuild=args.rebuild,
            )
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 0
