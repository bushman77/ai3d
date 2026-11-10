#!/usr/bin/env python3
"""Space Nova local image -> 3D -> Paint3D -> game GLB pipeline.

No third-party Python packages are required by THIS driver. It invokes the
user's existing Hunyuan3D, Paint3D and Blender environments separately.

GPU stages use the same low-memory settings already proven on RTX 3060 6 GB.
It never alters upstream repositories or original images/GLBs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# Allow the legacy script to run directly from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai3d.common import ensure_file, resolve
from ai3d.export.validation import readable_glb
from ai3d.pipeline_runner import Runner
from ai3d.optimization.blender import build_finalize_command

HOME = Path.home()
AI3D = HOME / "ai3d"
QWEN = HOME / "models/Qwen-Image-2512"
STAGES = ("reference", "cutout", "shape", "paint-mesh", "paint", "game")


def positive(value: str) -> int:
    out = int(value)
    if out <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return out


def arguments() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Local Space Nova asset factory: reference -> cutout -> Hunyuan -> Paint3D -> textured GLB"
    )
    p.add_argument("--name", required=True, help="Asset ID, e.g. mara_venn")
    inp = p.add_mutually_exclusive_group()
    inp.add_argument("--image", type=Path, help="Existing reference PNG/JPEG (recommended)")
    inp.add_argument("--prompt-file", type=Path, help="Qwen prompt.txt, requires --enable-qwen")
    p.add_argument("--enable-qwen", action="store_true", help="Explicitly opt in to Qwen generation (large memory use)")
    p.add_argument("--shape-mesh", type=Path, help="Reuse an existing raw shape GLB instead of Hunyuan")
    p.add_argument("--painted-mesh", type=Path, help="Reuse an existing fully painted GLB; skips generation and Paint3D")
    p.add_argument("--workdir", type=Path, default=AI3D / "pipeline_runs")
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
    return p.parse_args()


def should_stop(args, stage):
    return STAGES.index(args.stop_after) <= STAGES.index(stage)


def main():
    a = arguments()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.name):
        raise RuntimeError("--name must contain letters, numbers, hyphens, underscores only")
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

    home = resolve(a.workdir) / a.name
    if not a.dry_run:
        home.mkdir(parents=True, exist_ok=True)
    h = resolve(a.hunyuan)
    kit = resolve(a.aigamekit)
    bpy_script = Path(__file__).resolve().with_name("space_nova_blender_finalize.py")
    bpy_impl = PROJECT_ROOT / "ai3d/optimization/blender_finalize.py"
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
        cli = HOME / "ai-image/stable-diffusion.cpp/build/bin/sd-cli"
        ensure_file(cli, "sd-cli")
        if not shutil.which("systemd-run"):
            raise RuntimeError("systemd-run required for guarded Qwen. Use --image instead")
        qwen_cmd = ["systemd-run", "--user", "--scope", "-p", f"MemoryMax={a.qwen_ram}",
                    "-p", f"MemorySwapMax={a.qwen_swap}", str(cli),
                    "--diffusion-model", str(QWEN / "qwen-image-2512-Q3_K_M.gguf"),
                    "--llm", str(QWEN / "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"),
                    "--vae", str(QWEN / "qwen_image_vae.safetensors"),
                    "--backend", "cuda0", "--params-backend", "disk", "--max-vram", "-1",
                    "--diffusion-fa", "--cfg-scale", "2.5", "--sampling-method", "euler",
                    "--flow-shift", "3", "--steps", str(a.qwen_steps), "-t", "4",
                    "-W", str(a.qwen_width), "-H", str(a.qwen_height),
                    "--seed", "42", "-p", prompt.read_text(), "-o", str(reference)]
        runner.run("reference", [prompt, cli], [reference],
                   {"qwen": [a.qwen_width, a.qwen_height, a.qwen_steps, a.qwen_ram, a.qwen_swap]},
                   lambda: runner.command("reference", qwen_cmd, cwd=cli.parent))

    if reference:
        if should_stop(a, "reference"):
            print(f"\nReference: {reference}")
            return
        cutout = home / "02_cutout.png"
        hy_python = h / ".venv/bin/python"
        # A tiny inline helper avoids adding another heavy dependency to the host Python.
        script = """from pathlib import Path
from PIL import Image
from hy3dgen.rembg import BackgroundRemover
import sys
im = Image.open(sys.argv[1])
alpha = im.convert('RGBA').getchannel('A')
if alpha.getextrema()[0] < 250 or sys.argv[3] == 'skip':
    out = im.convert('RGBA')
    print('Using existing alpha / bypassing cutout')
else:
    print('Removing opaque background...')
    out = BackgroundRemover()(im.convert('RGB'))
out.save(sys.argv[2])
print('Alpha range:', out.getchannel('A').getextrema(), 'Size:', out.size)
"""
        cmd = [str(hy_python), "-c", script, str(reference), str(cutout), "skip" if a.no_cutout else "auto"]
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
            cmd = [str(hy_python), str(script), "--input", str(cutout),
                   "--output", str(raw), "--steps", str(a.shape_steps)]
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
        cmd = [blender, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", str(geometry_script), "--", "--input", str(raw),
               "--target-faces", str(a.paint_faces), "--output", str(paint_mesh)]
        runner.run("paint-mesh", [raw, geometry_script], [paint_mesh], {"faces": a.paint_faces},
                   lambda: runner.command("paint-mesh", cmd))
        if not a.dry_run:
            stages["paint-mesh"] = readable_glb(paint_mesh)
        if should_stop(a, "paint-mesh"):
            print(f"\nPrepared paint mesh: {paint_mesh}")
            return

        paint_python = kit / "Paint3D/.venv/bin/python"
        ensure_file(paint_python, "Paint3D Python")
        cmd = [str(paint_python), "-m", "paint3d", "texture", str(paint_mesh),
               "-i", str(cutout), "-o", str(painted), "--quality", a.quality,
               "--max-views", str(a.max_views), "--view-resolution", str(a.view_resolution),
               "--render-size", str(a.render_size), "--texture-size", str(a.texture_size),
               "--bake-exp", str(a.bake_exp), "--no-vramd", "--profile"]
        if a.category != "none":
            cmd += ["--category", a.category]
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
        ensure_file(bpy_impl, "AI3D Blender optimization backend")
        blender = shutil.which(a.blender) or a.blender
        cmd = build_finalize_command(blender, bpy_script, painted, game, a.game_faces)
        runner.run("game", [painted, bpy_script, bpy_impl], [game], {"faces": a.game_faces},
                   lambda: runner.command("game", cmd))

    if not a.dry_run:
        stages["game"] = readable_glb(game, need_texture=True)
        report = {"asset": a.name, "config": config, "stages": stages,
                  "timing": runner.timing,
                  "quality_notes": [
                      "Inspect front/side/back in Blender Material Preview (Z then M)",
                      "Confirm face resembles original; this is not automatically scored",
                      "Check texture seams on shoulders/hands/face before release",
                      "Check orientation, scale, origin and material consistency in Three.js",
                      "Humanoid GLB is NOT rigged or animated by this pipeline",
                  ]}
        (home / "report.json").write_text(json.dumps(report, indent=2))
        print("\nSUCCESS: textured game asset:", game)
        print("Size:", f"{game.stat().st_size / 1024:.0f} KiB")
        print("Triangles:", stages["game"]["triangles"])
        print("Texture images:", stages["game"]["images"])
        print("Report:", home / "report.json")
        print("NEXT: open Blender, import 06_game.glb, use Material Preview (Z then M)")
    else:
        print("\nDry run complete; nothing was generated.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
