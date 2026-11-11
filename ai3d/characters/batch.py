"""Sequential, card-driven multi-part asset generation using existing AI3D stages.

One part = one independently inspectable output run. This deliberately does
not assemble or rig components, since their attachment/scale requires a
separate alignment and acceptance workflow.
"""

from pathlib import Path

from ai3d.image.qwen import DEFAULT_MODEL_DIR, DEFAULT_SD_CLI
from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory
from ai3d.characters.reference import (
    compose_reference_prompt, run_reference, select_part_and_view,
)


def build_plan(
    card: dict,
    *,
    all_parts: bool = False,
    part_ids: list[str] | None = None,
    skip: list[str] | None = None,
    include_regions: bool = False,
    stop_after: str = "reference",
    run_prefix: str | None = None,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
) -> list[dict]:
    """Build a fully validated, deterministic plan without filesystem changes."""
    valid_stages = ("reference", "shape", "paint", "game")
    if stop_after not in valid_stages:
        raise RuntimeError(f"Unsupported target stage: {stop_after}")
    if all_parts == bool(part_ids):
        raise RuntimeError("Select either --all or one or more --part flags")
    parts = {part["id"]: part for part in card["parts"]}
    requested = list(parts) if all_parts else list(part_ids)
    omitted = set(skip or [])
    for part_id in requested + list(omitted):
        if part_id not in parts:
            raise RuntimeError(
                f"Unknown part {part_id!r}; available: {', '.join(parts)}"
            )
    prefix = run_prefix or card["id"]
    plan = []
    for part_id in dict.fromkeys(requested):
        if part_id in omitted:
            continue
        part, view = select_part_and_view(card, part_id)
        # Validate the prompt *before* any expensive inference begins.
        compose_reference_prompt(card, part, view)
        stage = (
            "reference"
            if part["kind"] == "region" and not include_regions
            else stop_after
        )
        name = f"{prefix}_{part_id}_{view}"
        folder = run_directory(name, output_dir)
        generation = part["generation"]
        geometry_backend = generation.get("geometry_backend")
        texture_backend = generation.get("texture_backend")
        if stage != "reference" and geometry_backend not in (None, "hunyuan"):
            raise RuntimeError(
                f"Part {part_id}: unsupported geometry_backend {geometry_backend!r}; "
                "this workflow currently supports Hunyuan only"
            )
        if stage in ("paint", "game") and texture_backend not in (None, "paint3d"):
            raise RuntimeError(
                f"Part {part_id}: unsupported texture_backend {texture_backend!r}; "
                "this workflow currently supports Paint3D only"
            )
        plan.append({
            "part_id": part_id,
            "kind": part["kind"],
            "view": view,
            "name": name,
            "folder": folder,
            "stage": stage,
            "generation": generation,
        })
    if not plan:
        raise RuntimeError("No parts selected after --skip")
    return plan


def _option(value: int | None, default: int) -> int:
    return value if value is not None else default


def generate_character(
    card: dict,
    card_path: Path,
    *,
    all_parts: bool = False,
    part_ids: list[str] | None = None,
    skip: list[str] | None = None,
    include_regions: bool = False,
    stop_after: str = "reference",
    run_prefix: str | None = None,
    output_dir: Path = DEFAULT_OUTPUT_ROOT,
    sd_cli: Path = DEFAULT_SD_CLI,
    qwen_model_dir: Path = DEFAULT_MODEL_DIR,
    hunyuan: Path | None = None,
    aigamekit: Path | None = None,
    blender: str = "blender",
    qwen_width: int = 384,
    qwen_height: int = 384,
    qwen_steps: int = 12,
    qwen_ram: str = "10G",
    qwen_swap: str = "1G",
    shape_steps: int = 20,
    paint_faces: int = 40000,
    game_faces: int = 15000,
    view_resolution: int = 256,
    texture_size: int = 1024,
    render_size: int = 512,
    quality: str = "fast",
    max_views: int = 2,
    paint_debug: bool = False,
    resume: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    """Generate one character's parts *serially* to respect limited VRAM."""
    if resume and force:
        raise RuntimeError("Use either --resume or --force, not both")
    if any(
        type(value) is not int or value < 1 for value in (
            qwen_width, qwen_height, qwen_steps, shape_steps, paint_faces,
            game_faces, view_resolution, texture_size, render_size, max_views,
        )
    ):
        raise RuntimeError("All sizes, steps and view counts must be positive integers")
    if quality not in ("fast", "low", "medium", "high", "highest"):
        raise RuntimeError("Unknown Paint3D quality setting")

    plan = build_plan(
        card, all_parts=all_parts, part_ids=part_ids, skip=skip,
        include_regions=include_regions, stop_after=stop_after,
        run_prefix=run_prefix, output_dir=output_dir,
    )

    # Fail before launching any GPU process if a run would be overwritten.
    # The stage runner handles individual file checks once started.
    for item in plan:
        folder = item["folder"]
        if folder.is_symlink():
            raise RuntimeError(f"Output run is a symlink: {folder}")
        if folder.exists() and not folder.is_dir():
            raise RuntimeError(f"Output run is not a directory: {folder}")
        if folder.exists() and not (resume or force or dry_run):
            raise RuntimeError(
                f"Output run already exists: {folder}; "
                "choose another --run-prefix or explicitly --resume/--force"
            )

    print(f"Character: {card['name']} ({card['id']})")
    print(f"Selected parts: {len(plan)} | requested target: {stop_after}")
    print("One part at a time: Qwen reference -> Hunyuan shape -> Paint3D -> game GLB")
    print("Assembly/rigging is not performed.")
    for item in plan:
        print(
            f"  {item['part_id']:<16} {item['kind']:<11} "
            f"up to {item['stage']:<9} {item['folder']}"
        )
    if not include_regions and any(item["kind"] == "region" for item in plan):
        print("Region parts produce references only; use --include-regions to experiment with isolated meshes.")

    from pipelines.image_to_3d import main as pipeline_main

    for index, item in enumerate(plan, start=1):
        print(f"\n[{index}/{len(plan)}] {item['part_id']} ({item['stage']})", flush=True)
        ref = run_reference(
            card, card_path,
            part_id=item["part_id"], view=item["view"], name=item["name"],
            output_dir=output_dir, sd_cli=sd_cli, model_dir=qwen_model_dir,
            width=_option(item["generation"].get("reference_width"), qwen_width),
            height=_option(item["generation"].get("reference_height"), qwen_height),
            steps=qwen_steps,
            ram_limit=qwen_ram, swap_limit=qwen_swap,
            resume=resume, force=force, dry_run=dry_run,
        )
        if item["stage"] == "reference":
            continue

        gen = item["generation"]
        args = [
            "--name", item["name"],
            "--image", str(ref),
            "--output-dir", str(output_dir),
            "--stop-after", item["stage"],
            "--shape-steps", str(_option(gen.get("shape_steps"), shape_steps)),
            "--paint-faces", str(_option(gen.get("target_triangles"), paint_faces)),
            "--game-faces", str(game_faces),
            "--view-resolution", str(_option(gen.get("view_resolution"), view_resolution)),
            "--texture-size", str(texture_size),
            "--render-size", str(render_size),
            "--quality", quality,
            "--max-views", str(max_views),
            "--category", (
                "prop" if item["kind"] == "attachment"
                else "humanoid" if card["category"] == "humanoid" else "none"
            ),
            "--blender", blender,
        ]
        if hunyuan is not None:
            args.extend(["--hunyuan", str(hunyuan)])
        if aigamekit is not None:
            args.extend(["--aigamekit", str(aigamekit)])
        if paint_debug and item["stage"] in ("paint", "game"):
            args.append("--paint-debug")
        if force:
            args.append("--force")
        else:
            # A Qwen reference was just written in the same run. Resume all
            # subsequent model stages without clobbering previously cached files.
            args.append("--resume")
        if dry_run:
            print("Dry run: would invoke ai3d generate " + " ".join(args))
        else:
            pipeline_main(args, prog="ai3d generate")
    if dry_run:
        print("\nDry run completed; nothing generated.")
    else:
        print("\nCompleted requested part stages. Inspect each result before assembly.")
    return plan
