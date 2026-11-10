#!/usr/bin/env python3
"""AI3D: local image-to-3D orchestration with isolated inference backends.

The controlling Python process requires only the standard library.
Hunyuan, Paint3D, Qwen, and Blender run as independent subprocesses.
Inputs and third-party upstream checkouts are never modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Support direct script invocation from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai3d.common import ensure_file, resolve
from ai3d.export.validation import readable_glb
from ai3d.pipeline_runner import Runner
from ai3d.optimization.blender import build_finalize_command
from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory
from ai3d.image.qwen import build_qwen_command, DEFAULT_SD_CLI, DEFAULT_MODEL_DIR
from ai3d.image.background import build_cutout_command
from ai3d.geometry.hunyuan import build_shape_command, build_prepaint_command
from ai3d.textures.paint3d import build_texture_command

AI3D = PROJECT_ROOT
STAGES = ("reference", "cutout", "shape", "paint-mesh", "paint", "game")


def positive(value: str) -> int:
    out = int(value)
    if out <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return out


def arguments(argv: list[str] | None = None, *, prog: str | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog=prog,
        description="AI3D asset pipeline: reference -> cutout -> geometry -> textures -> GLB"
    )
    p.add_argument("--name", required=True, help="Asset ID, e.g. example_character")
    inp = p.add_mutually_exclusive_group()
    inp.add_argument("--image", type=Path, help="Existing reference PNG/JPEG (recommended)")
    inp.add_argument("--prompt-file", type=Path, help="Qwen prompt.txt, requires --enable-qwen")
    p.add_argument("--enable-qwen", action="store_true", help="Explicitly opt in to Qwen generation (large memory use)")
    p.add_argument("--sd-cli", type=Path, default=DEFAULT_SD_CLI,
                   help="Path to a CUDA-capable stable-diffusion.cpp sd-cli executable")
    p.add_argument("--qwen-model-dir", type=Path, default=DEFAULT_MODEL_DIR,
                   help="Directory containing Qwen image diffusion, LLM and VAE weights")
    p.add_argument("--shape-mesh", type=Path, help="Reuse an existing raw shape GLB instead of Hunyuan")
    p.add_argument("--painted-mesh", type=Path, help="Reuse an existing fully painted GLB; skips generation and Paint3D")
    p.add_argument("--output-dir", "--workdir", dest="workdir", metavar="PATH", type=Path,
                   default=DEFAULT_OUTPUT_ROOT,
                   help="Root for all generated run files (default: <ai3d>/outputs)")
    p.add_argument("--hunyuan", type=Path, default=AI3D / "Hunyuan3D-2")
    p.add_argument("--aigamekit", type=Path, default=AI3D / "AiGameKit")
    p.add_argument("--blender", default="blender")
    p.add_argument("--no-cutout", action="store_true", help="Pass original image unchanged (not recommended for opaque backgrounds)")
    p.add_argument("--shape-steps", type=positive, default=20)
    p.add_argument("--paint-faces", type=positive, default=40000, help="Geometry detail sent to Paint3D")
    p.add_argument("--game-faces", type=positive, default=15000, help="Final target triangle count")
    p.add_argument("--category", choices=("humanoid", "prop", "weapon", "none"), default="humanoid")
    p.add_argument("--quality", choices=("fast", "low", "medium", "high", "highest"), default="fast")
    p.add_argument("--max-views", type=positive, default=2)
    p.add_argument("--view-resolution", type=positive, default=256)
    p.add_argument("--render-size", type=positive, default=512)
    p.add_argument("--texture-size", type=positive, default=1024)
    p.add_argument("--bake-exp", type=positive, default=6)
    p.add_argument("--stop-after", choices=STAGES, default="game", help="Stop at quality gate")
    p.add_argument("--resume", action="store_true", help="Skip stages only when inputs/options match recorded stage manifest")
    p.add_argument("--force", action="store_true", help="Rebuild all requested stages (overwriting only run outputs)")
    p.add_argument("--dry-run", action="store_true", help="Print stage commands without running them")
    p.add_argument("--qwen-width", type=positive, default=384)
    p.add_argument("--qwen-height", type=positive, default=576)
    p.add_argument("--qwen-steps", type=positive, default=12)
    p.add_argument("--qwen-ram", default="10G", help="systemd MemoryMax for optional Qwen stage")
    p.add_argument("--qwen-swap", default="1G", help="systemd MemorySwapMax for optional Qwen stage")
    p.add_argument("--no-finalize", action="store_true", help="Use full painted GLB as final; skip polygon reduction")
    return p.parse_args(argv)


def should_stop(args, stage):
    return STAGES.index(args.stop_after) <= STAGES.index(stage)


def main(argv: list[str] | None = None, *, prog: str | None = None):
    a = arguments(argv, prog=prog)
    if a.force and a.resume:
        raise RuntimeError("Choose either --force or --resume, not both")
    if a.prompt_file and not a.enable_qwen:
        raise RuntimeError("Qwen is opt-in: add --enable-qwen to use --prompt-file")
    if a.enable_qwen and not a.prompt_file:
        raise RuntimeError("--enable-qwen requires --prompt-file")
    if not (a.image or a.prompt_file or a.painted_mesh):
        raise RuntimeError("Provide --image, --prompt-file with --enable-qwen, or --painted-mesh")
    if a.shape_mesh and a.painted_mesh:
        raise RuntimeError("Choose either --shape-mesh or --painted-mesh")

    home = run_directory(a.name, a.workdir)
    if not a.dry_run:
        home.mkdir(parents=True, exist_ok=True)
    h = resolve(a.hunyuan)
    kit = resolve(a.aigamekit)
    bpy_script = PROJECT_ROOT / "ai3d/optimization/blender_finalize.py"
    runner = Runner(home, a.resume, a.force, a.dry_run)
    config = vars(a).copy()
    config = {k: str(v) if isinstance(v, Path) else v for k, v in config.items()}
    stages = {}
    reference = None
    cutout = None
    raw = None
    paint_mesh = None
    painted = home / "05_painted.glb"
    game = home / "06_game.glb"

    if a.image:
        image_in = resolve(a.image)
        ensure_file(image_in, "Reference image")
        reference = home / ("01_reference" + image_in.suffix.lower())
        runner.run("reference", [image_in], [reference], {"copy": True},
                   lambda: runner.copy(image_in, reference))
    elif a.prompt_file:
        prompt = resolve(a.prompt_file)
        ensure_file(prompt, "Qwen prompt")
        reference = home / "01_reference.png"
        cli = resolve(a.sd_cli)
        weights = resolve(a.qwen_model_dir)
        ensure_file(cli, "sd-cli")
        if not shutil.which("systemd-run"):
            raise RuntimeError("systemd-run required for guarded Qwen. Use --image instead")
        qwen_cmd = build_qwen_command(
            cli, weights, prompt.read_text(), reference,
            width=a.qwen_width, height=a.qwen_height, steps=a.qwen_steps,
            ram_limit=a.qwen_ram, swap_limit=a.qwen_swap,
        )
        model_files = [
            weights / name for name in (
                "qwen-image-2512-Q3_K_M.gguf",
                "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
                "qwen_image_vae.safetensors",
            )
        ]
        runner.run(
            "reference", [prompt, cli, *model_files], [reference],
            {"qwen": [a.qwen_width, a.qwen_height, a.qwen_steps, a.qwen_ram, a.qwen_swap],
             "sd_cli": str(cli), "models": str(weights)},
            lambda: runner.command("reference", qwen_cmd, cwd=cli.parent),
        )

    if reference:
        if should_stop(a, "reference"):
            print(f"\nReference: {reference}")
            return
        cutout = home / "02_cutout.png"
        hy_python = h / ".venv/bin/python"
        cmd = build_cutout_command(hy_python, reference, cutout, skip=a.no_cutout)
        runner.run("cutout", [reference, hy_python], [cutout], {"skip": a.no_cutout},
                   lambda: runner.command("cutout", cmd, cwd=h))
        if should_stop(a, "cutout"):
            print(f"\nCutout: {cutout}")
            return

    if a.painted_mesh:
        existing = resolve(a.painted_mesh)
        readable_glb(existing, need_texture=True)
        runner.run("paint", [existing], [painted], {"from": "existing"},
                   lambda: runner.copy(existing, painted))
    else:
        assert cutout is not None
        raw = home / "03_shape.glb"
        if a.shape_mesh:
            existing = resolve(a.shape_mesh)
            readable_glb(existing)
            runner.run("shape", [existing], [raw], {"from": "existing"},
                       lambda: runner.copy(existing, raw))
        else:
            hy_python = h / ".venv/bin/python"
            script = h / "first_mesh.py"
            ensure_file(script, "Hunyuan wrapper first_mesh.py")
            cmd = build_shape_command(hy_python, script, cutout, raw, steps=a.shape_steps)
            env = os.environ.copy()
            env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
            runner.run("shape", [cutout, script], [raw], {"steps": a.shape_steps},
                       lambda: runner.command("shape", cmd, cwd=h, env=env))
        if not a.dry_run:
            stages["shape"] = readable_glb(raw)
        if should_stop(a, "shape"):
            print(f"\nShape: {raw}")
            return

        paint_mesh = home / "04_paint_mesh.glb"
        geometry_script = h / "optimize_mesh.py"
        ensure_file(geometry_script, "Existing geometry-only optimizer")
        blender = shutil.which(a.blender) or a.blender
        cmd = build_prepaint_command(blender, geometry_script, raw, paint_mesh, target_faces=a.paint_faces)
        runner.run("paint-mesh", [raw, geometry_script], [paint_mesh], {"faces": a.paint_faces},
                   lambda: runner.command("paint-mesh", cmd))
        if not a.dry_run:
            stages["paint-mesh"] = readable_glb(paint_mesh)
        if should_stop(a, "paint-mesh"):
            print(f"\nPrepared paint mesh: {paint_mesh}")
            return

        paint_python = kit / "Paint3D/.venv/bin/python"
        ensure_file(paint_python, "Paint3D Python")
        cmd = build_texture_command(
            paint_python, paint_mesh, cutout, painted,
            quality=a.quality, category=a.category, max_views=a.max_views,
            view_resolution=a.view_resolution, render_size=a.render_size,
            texture_size=a.texture_size, bake_exp=a.bake_exp,
        )
        env = os.environ.copy()
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        runner.run("paint", [paint_mesh, cutout], [painted],
                   {"quality": a.quality, "views": a.max_views,
                    "view_res": a.view_resolution, "render": a.render_size,
                    "texture": a.texture_size, "bake_exp": a.bake_exp, "category": a.category},
                   lambda: runner.command("paint", cmd, cwd=kit, env=env))

    if not a.dry_run:
        stages["paint"] = readable_glb(painted, need_texture=True)
    if should_stop(a, "paint"):
        print(f"\nTextured GLB: {painted}")
        return

    if a.no_finalize:
        runner.run("game", [painted], [game], {"copy": True}, lambda: runner.copy(painted, game))
    else:
        ensure_file(bpy_script, "Textured Blender finalizer")
        blender = shutil.which(a.blender) or a.blender
        cmd = build_finalize_command(blender, bpy_script, painted, game, a.game_faces)
        runner.run("game", [painted, bpy_script], [game], {"faces": a.game_faces},
                   lambda: runner.command("game", cmd))

    if not a.dry_run:
        stages["game"] = readable_glb(game, need_texture=True)
        report = {"asset": a.name, "config": config, "stages": stages,
                  "timing": runner.timing,
                  "quality_notes": [
                      "Inspect front/side/back in Blender Material Preview (Z then M)",
                      "Compare shape and visual details against the source image",
                      "Check UV seams and texture coverage before release",
                      "Check orientation, scale, origin and materials in the target application",
                      "This pipeline does not perform rigging or animation",
                  ]}
        (home / "report.json").write_text(json.dumps(report, indent=2))
        print("\nSUCCESS: textured 3D asset:", game)
        print("Size:", f"{game.stat().st_size / 1024:.0f} KiB")
        print("Triangles:", stages["game"]["triangles"])
        print("Texture images:", stages["game"]["images"])
        print("Report:", home / "report.json")
        print("NEXT: inspect 06_game.glb in Blender Material Preview (Z then M)")
    else:
        print("\nDry run complete; nothing was generated.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
