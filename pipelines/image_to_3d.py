#!/usr/bin/env python3
"""AI3D: one image in, one rigged game-ready character out.

    reference -> views -> cutout -> shape -> paint-mesh -> paint -> game -> rig -> report

reference   copy --image, or Qwen text-to-image from --prompt-file
views       Qwen-Image-Edit draws left/back/right of the SAME character
            (or use your own with --view-left/--view-back/--view-right)
cutout      background removal for every view
shape       Hunyuan3D-2mv from all views (Hunyuan3D-2mini if front only)
paint-mesh  Blender clean-up and reduction for Paint3D
paint       Paint3D texturing
texture-views  Qwen-Image-Edit redraws every view at 1024 px (same content)
game        Blender: watertight quad mesh + baked colour/normal/roughness,
            colour painted straight from the sharp views
rig         Blender: Mixamo-named skeleton + automatic weights + test action
report      Blender: measurements, silhouette match, preview renders,
            report.json and index.html

All settings live in config/default.json (override with --config / --set).
The controlling process is standard-library Python; every heavy tool runs
as a subprocess in its own environment. Inputs are never modified.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import secrets
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai3d.blender.commands import blender_command  # noqa: E402
from ai3d.common import ensure_file, resolve  # noqa: E402
from ai3d.config import load_profile, repo_path  # noqa: E402
from ai3d.export.validation import readable_glb  # noqa: E402
from ai3d.geometry.hunyuan import build_hunyuan_shape_command  # noqa: E402
from ai3d.image.qwen import (  # noqa: E402
    UPSCALE_PROMPT, build_qwen_command, build_qwen_edit_command, split_prompt, view_prompt,
)
from ai3d.optimization.blender import build_finalize_command  # noqa: E402
from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory  # noqa: E402
from ai3d.pipeline_runner import Runner  # noqa: E402
from ai3d.textures.diagnostics import expected_debug_images, paint_debug_environment  # noqa: E402
from ai3d.textures.paint3d import build_texture_command  # noqa: E402

STAGES = ("reference", "views", "cutout", "shape", "paint-mesh", "paint", "texture-views",
          "game", "rig", "report")
ANGLES = ("left", "back", "right")
SHAPE_SCRIPT = PROJECT_ROOT / "backends" / "hunyuan_shape.py"
CUTOUT_SCRIPT = PROJECT_ROOT / "backends" / "cutout.py"
FINALIZE_SCRIPT = PROJECT_ROOT / "ai3d" / "optimization" / "blender_finalize.py"


def arguments(argv: list[str] | None = None, *, prog: str | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=prog, description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Stages: " + " -> ".join(STAGES) + "\nSettings: config/default.json",
    )
    p.add_argument("--name", required=True, help="Run name; files go to outputs/<name>/")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--image", type=Path, help="Front reference image (PNG/JPEG)")
    src.add_argument("--prompt-file", type=Path, help="Text prompt for Qwen text-to-image")
    p.add_argument("--enable-qwen", action="store_true", help=argparse.SUPPRESS)  # old flag, no-op
    for angle in ANGLES:
        p.add_argument(f"--view-{angle}", type=Path, help=f"Your own {angle} view image")
    p.add_argument("--no-views", action="store_true", help="Front image only (Hunyuan3D-2mini)")
    p.add_argument("--redo-view", action="append", choices=("front", *ANGLES), default=[],
                   help="Regenerate this view with a new random seed (repeatable); "
                        "use with --resume so the other views are kept")
    p.add_argument("--shape-mesh", type=Path, help="Reuse an existing raw shape GLB")
    p.add_argument("--painted-mesh", type=Path, help="Reuse an existing painted GLB (skips to game)")
    p.add_argument("--config", type=Path, help="Profile merged over config/default.json")
    p.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE",
                   help="Override one setting, e.g. --set shape.steps=50 (repeatable)")
    p.add_argument("--seed", type=int, help="Overrides config seed")
    p.add_argument("--no-retopo", action="store_true", help="Old behaviour: decimate only")
    p.add_argument("--no-rig", action="store_true", help="Skip the rig stage")
    p.add_argument("--paint-debug", action="store_true",
                   help="Save Paint3D per-view and UV bake images under paint_debug/")
    p.add_argument("--stop-after", choices=STAGES, default="report")
    p.add_argument("--output-dir", "--workdir", dest="workdir", metavar="PATH", type=Path,
                   default=DEFAULT_OUTPUT_ROOT, help="Root for runs (default: <ai3d>/outputs)")
    action = p.add_mutually_exclusive_group()
    action.add_argument("--resume", action="store_true",
                        help="Skip stages whose inputs and settings are unchanged")
    action.add_argument("--force", action="store_true", help="Rerun every requested stage")
    p.add_argument("--dry-run", action="store_true", help="Show the plan and commands only")
    return p.parse_args(argv)


def settings(a: argparse.Namespace) -> dict:
    overrides = list(a.set)
    if a.seed is not None:
        overrides.append(f"seed={a.seed}")
    if a.no_retopo:
        overrides.append("retopo.enabled=false")
    if a.no_rig:
        overrides.append("rig.enabled=false")
    if a.no_views:
        overrides.append("views.enabled=false")
    if a.paint_debug:
        overrides.append("paint.debug=true")
    return load_profile(a.config, overrides)


class Plan:
    """Resolved tool and model paths for one run, plus a preflight check."""

    def __init__(self, a, cfg):
        P = cfg["paths"]
        self.blender = shutil.which(P["blender"]) or P["blender"]
        self.hunyuan = repo_path(P["hunyuan"])
        self.hy_python = self.hunyuan / ".venv/bin/python"
        self.kit = repo_path(P["aigamekit"])
        self.paint_python = self.kit / "Paint3D/.venv/bin/python"
        self.sd_cli = repo_path(P["sd_cli"])
        qdir = repo_path(P["qwen_model_dir"])
        edir = repo_path(P["qwen_edit_model_dir"])
        R, V = cfg["reference"], cfg["views"]
        self.qwen = {k: qdir / R[k] for k in ("diffusion_model", "llm", "vae")}
        self.edit = {"diffusion_model": edir / V["diffusion_model"],
                     "llm_vision": edir / V["llm_vision"],
                     "llm": self.qwen["llm"], "vae": self.qwen["vae"]}
        self.models_root = repo_path(P["hunyuan_models"])
        self.checks: list[tuple[str, Path | str, bool]] = []

    def hunyuan_model_path(self, model: str) -> Path | None:
        folder = self.models_root / ("Hunyuan3D-2mv" if model.startswith("mv") else "Hunyuan3D-2mini")
        return folder if folder.is_dir() else None

    def need(self, label: str, path: Path) -> None:
        self.checks.append((label, path, Path(path).is_file()))

    def need_blender(self) -> None:
        self.checks.append(("Blender", self.blender, shutil.which(self.blender) is not None))

    def report(self, dry: bool) -> None:
        missing = [c for c in self.checks if not c[2]]
        print("\nPreflight:")
        for label, path, ok in self.checks:
            print(f"  [{'ok' if ok else 'MISSING'}] {label}: {path}")
        if missing and not dry:
            raise RuntimeError(
                "Missing tools/models listed above. Fix the paths in your config "
                "(see config/default.json 'paths'), or skip that stage "
                "(--no-views, --no-rig, --image instead of --prompt-file).")


def main(argv: list[str] | None = None, *, prog: str | None = None):
    a = arguments(argv, prog=prog)
    cfg = settings(a)
    if not (a.image or a.prompt_file or a.painted_mesh):
        raise RuntimeError("Provide --image, --prompt-file or --painted-mesh")
    if a.shape_mesh and not (a.image or a.prompt_file):
        raise RuntimeError("--shape-mesh still needs --image (Paint3D uses the front cutout)")
    if a.shape_mesh and a.painted_mesh:
        raise RuntimeError("Choose either --shape-mesh or --painted-mesh")
    if cfg["paint"]["debug"] and a.painted_mesh:
        raise RuntimeError("--paint-debug needs a Paint3D run; --painted-mesh skips painting")
    given_views = {k: getattr(a, f"view_{k}") for k in ANGLES if getattr(a, f"view_{k}")}
    clash = set(a.redo_view) & set(given_views)
    if clash:
        raise RuntimeError(f"--redo-view {', '.join(sorted(clash))} conflicts with your own --view-* image")
    if given_views and not (a.image or a.prompt_file):
        raise RuntimeError("--view-* images need a front --image or --prompt-file too")

    home = run_directory(a.name, a.workdir)
    plan = Plan(a, cfg)
    seed = cfg["seed"]
    stop = STAGES.index(a.stop_after)
    wants = lambda stage: STAGES.index(stage) <= stop  # noqa: E731
    stats_dir = home / "stats"

    # ---- decide what will run, then preflight before touching the GPU ------
    make_reference = bool(a.prompt_file)
    gen_views = []
    if (a.image or a.prompt_file) and cfg["views"]["enabled"] and wants("views"):
        gen_views = [v for v in cfg["views"]["angles"] if v not in given_views]
    need_mesh_stages = not a.painted_mesh
    if make_reference:
        plan.need("sd-cli", plan.sd_cli)
        for k, path in plan.qwen.items():
            plan.need(f"Qwen {k}", path)
    TV = cfg["texture_views"]
    upscale = (TV["enabled"] and TV["upscale"] and wants("texture-views")
               and bool(a.image or a.prompt_file))
    if gen_views or upscale:
        plan.need("sd-cli", plan.sd_cli)
        for k, path in plan.edit.items():
            plan.need(f"Qwen-Image-Edit {k} (views)", path)
    if upscale and need_mesh_stages:
        plan.need("Hunyuan3D-2 python", plan.hy_python)
    if need_mesh_stages and wants("cutout"):
        plan.need("Hunyuan3D-2 python", plan.hy_python)
    if need_mesh_stages and wants("paint-mesh"):
        plan.need_blender()
    if need_mesh_stages and wants("paint"):
        plan.need("Paint3D python", plan.paint_python)
    if wants("game"):
        plan.need_blender()
    for label, path in (("--image", a.image), ("--prompt-file", a.prompt_file),
                        ("--shape-mesh", a.shape_mesh), ("--painted-mesh", a.painted_mesh),
                        *[(f"--view-{k}", v) for k, v in given_views.items()]):
        if path:
            plan.need(label, resolve(path))
    plan.checks = list(dict.fromkeys(plan.checks))
    plan.report(a.dry_run)
    runner = Runner(home, a.resume, a.force, a.dry_run)
    if not a.dry_run:
        home.mkdir(parents=True, exist_ok=True)
        stats_dir.mkdir(exist_ok=True)
        (home / "settings.json").write_text(json.dumps(cfg, indent=2) + "\n")

    # Seeds per view (and "front" for a text-to-image reference), so redoing
    # one picture with a new random seed keeps the rest.
    seeds_file = home / "view_seeds.json"
    view_seeds_early = json.loads(seeds_file.read_text()) if seeds_file.is_file() else {}
    if "front" in a.redo_view:
        if not a.prompt_file:
            raise RuntimeError("--redo-view front only works with --prompt-file "
                               "(with --image the front is your picture)")
        view_seeds_early["front"] = secrets.randbelow(2**31)
        print(f"[redo] front image with seed {view_seeds_early['front']}")
        if not a.dry_run:
            (home / "01_reference.png").unlink(missing_ok=True)
            seeds_file.write_text(json.dumps(view_seeds_early, indent=2) + "\n")

    painted = home / "05_painted.glb"
    front_cut = home / "02_cutout.png"
    cutouts: dict[str, Path] = {}

    # ---- reference -----------------------------------------------------------
    if a.image or a.prompt_file:
        if a.image:
            image_in = resolve(a.image)
            reference = home / ("01_reference" + image_in.suffix.lower())
            if not a.dry_run and image_in != reference.resolve():
                ensure_file(image_in, "Reference image")
            runner.run("reference", [image_in], [reference], {"copy": True},
                       lambda: runner.copy(image_in, reference))
        else:
            R = cfg["reference"]
            reference = home / "01_reference.png"
            prompt = resolve(a.prompt_file)
            positive, negative = split_prompt(prompt.read_text())
            ref_seed = view_seeds_early.get("front", seed)
            cmd = build_qwen_command(plan.sd_cli, plan.qwen["diffusion_model"].parent,
                                     positive, reference, width=R["width"],
                                     height=R["height"], steps=R["steps"],
                                     ram_limit=R["ram_limit"], swap_limit=R["swap_limit"])
            cmd[cmd.index("--seed") + 1] = str(ref_seed)
            cmd[cmd.index("--cfg-scale") + 1] = str(R["cfg_scale"])
            for flag, key in (("--diffusion-model", "diffusion_model"), ("--llm", "llm"), ("--vae", "vae")):
                cmd[cmd.index(flag) + 1] = str(plan.qwen[key])
            cmd[cmd.index("-o"):cmd.index("-o")] = ["--vae-tiling"]
            if negative:
                cmd[cmd.index("-o"):cmd.index("-o")] = ["-n", negative]
            runner.run_cmd("reference", [prompt, *plan.qwen.values()], [reference],
                           {"reference": R, "seed": ref_seed}, cmd, cwd=plan.sd_cli.parent)
        if not wants("views"):
            return finish(a, home, f"Reference: {reference}")

        # ---- views -------------------------------------------------------------
        views: dict[str, Path] = {}
        for angle, path in given_views.items():
            src = resolve(path)
            dst = home / f"01_view_{angle}{src.suffix.lower()}"
            runner.run(f"views-{angle}", [src], [dst], {"copy": True},
                       lambda s=src, d=dst: runner.copy(s, d))
            views[angle] = dst
        V = cfg["views"]
        view_seeds = dict(view_seeds_early)
        for angle in [v for v in a.redo_view if v != "front"]:
            view_seeds[angle] = secrets.randbelow(2**31)
            print(f"[redo] {angle} view with seed {view_seeds[angle]}")
            if not a.dry_run:
                (home / f"01_view_{angle}.png").unlink(missing_ok=True)
        if a.redo_view and not a.dry_run:
            seeds_file.write_text(json.dumps(view_seeds, indent=2) + "\n")
        for angle in gen_views:
            out = home / f"01_view_{angle}.png"
            angle_seed = view_seeds.get(angle, seed)
            cmd = build_qwen_edit_command(
                plan.sd_cli, reference=reference, prompt=view_prompt(angle), output=out,
                size=V["size"], steps=V["steps"], cfg_scale=V["cfg_scale"], seed=angle_seed,
                vae_tiling=V["vae_tiling"],
                ram_limit=cfg["reference"]["ram_limit"],
                swap_limit=cfg["reference"]["swap_limit"], **plan.edit)
            runner.run_cmd(f"views-{angle}", [reference, *plan.edit.values()], [out],
                           # vae_tiling changes memory use, not the picture: leave it out
                           # so --resume keeps views generated before it existed
                           {"views": {k: v for k, v in V.items() if k != "vae_tiling"},
                            "seed": angle_seed, "angle": angle}, cmd,
                           cwd=plan.sd_cli.parent)
            views[angle] = out
        if not wants("cutout"):
            names = ", ".join(str(v) for v in views.values()) or "none"
            return finish(a, home, f"Reference: {reference}\nViews: {names}\n"
                                   "Check every view shows the same character before --resume.")

        # ---- cutout ------------------------------------------------------------
        for angle, image in [("front", reference), *views.items()]:
            out = front_cut if angle == "front" else home / f"02_cutout_{angle}.png"
            cmd = [plan.hy_python, CUTOUT_SCRIPT, image, out, "auto"]
            label = "cutout" if angle == "front" else f"cutout-{angle}"
            runner.run_cmd(label, [image, plan.hy_python], [out], {}, cmd, cwd=plan.hunyuan)
            cutouts[angle] = out
        if not wants("shape"):
            return finish(a, home, f"Cutouts: {', '.join(str(c) for c in cutouts.values())}")

    # ---- shape -> paint-mesh -> paint ---------------------------------------------
    if a.painted_mesh:
        existing = resolve(a.painted_mesh)
        if not a.dry_run:
            readable_glb(existing, need_texture=True)
        runner.run("paint", [existing], [painted], {"from": "existing"},
                   lambda: runner.copy(existing, painted))
    else:
        raw = home / "03_shape.glb"
        S = cfg["shape"]
        side_views = {k: v for k, v in cutouts.items() if k != "front"}
        model = S["model"]
        if model == "auto":
            model = "mv" if side_views else "mini"
        if a.shape_mesh:
            existing = resolve(a.shape_mesh)
            runner.run("shape", [existing], [raw], {"from": "existing"},
                       lambda: runner.copy(existing, raw))
        else:
            if not model.startswith("mv"):
                side_views = {}
            cmd = build_hunyuan_shape_command(
                plan.hy_python, SHAPE_SCRIPT, raw, front=front_cut,
                left=side_views.get("left"), back=side_views.get("back"),
                right=side_views.get("right"), model=model,
                model_path=plan.hunyuan_model_path(model), steps=S["steps"],
                octree_resolution=S["octree_resolution"], num_chunks=S["num_chunks"],
                guidance_scale=S["guidance_scale"], seed=seed,
                remove_floaters=S["remove_floaters"], low_vram=S["low_vram"])
            env = os.environ.copy()
            env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
            runner.run_cmd("shape", [front_cut, *side_views.values(), SHAPE_SCRIPT], [raw],
                           {"shape": S, "model": model, "seed": seed}, cmd,
                           cwd=plan.hunyuan, env=env)
        if not wants("paint-mesh"):
            return finish(a, home, f"Shape: {raw}  (open in Blender, solid view, all sides)")

        paint_mesh = home / "04_paint_mesh.glb"
        faces = cfg["paint_mesh"]["target_faces"]
        cmd = blender_command(plan.blender, "prepaint.py", [
            "--input", raw, "--output", paint_mesh, "--target-faces", faces,
            "--stats", stats_dir / "paint_mesh.json"])
        runner.run_cmd("paint-mesh", [raw], [paint_mesh], {"faces": faces, "v": 2}, cmd)
        if not wants("paint"):
            return finish(a, home, f"Paint mesh: {paint_mesh}")

        T = cfg["paint"]
        cmd = build_texture_command(
            plan.paint_python, paint_mesh, front_cut, painted, quality=T["quality"],
            category=T["category"], max_views=T["max_views"],
            view_resolution=T["view_resolution"], render_size=T["render_size"],
            texture_size=T["texture_size"], bake_exp=T["bake_exp"])
        env = os.environ.copy()
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        env = paint_debug_environment(env, home, enabled=T["debug"])
        outputs = [painted, *expected_debug_images(home)] if T["debug"] else [painted]
        runner.run_cmd("paint", [paint_mesh, front_cut], outputs, {"paint": T}, cmd, cwd=plan.kit, env=env)
    if not wants("texture-views"):
        return finish(a, home, f"Textured GLB: {painted}")

    # ---- texture-views: sharp copies of every view for projection ---------------
    project_views: list[tuple[str, Path]] = []
    sources = []
    if TV["enabled"] and (a.image or a.prompt_file):
        sources = [("front", reference, front_cut)]
        for angle in ANGLES:
            if angle in views:
                sources.append((angle, views[angle], cutouts.get(angle)))
    for kind, image, cut in sources:
        if TV["upscale"]:
            hd = home / f"01_hd_{kind}.png"
            cmd = build_qwen_edit_command(
                plan.sd_cli, reference=image, prompt=UPSCALE_PROMPT, output=hd,
                size=TV["size"], steps=TV["steps"], cfg_scale=TV["cfg_scale"], seed=seed,
                vae_tiling=TV["vae_tiling"],
                ram_limit=cfg["reference"]["ram_limit"],
                swap_limit=cfg["reference"]["swap_limit"], **plan.edit)
            runner.run_cmd(f"texture-views-{kind}", [image, *plan.edit.values()], [hd],
                           {"texture_views": TV, "seed": seed}, cmd, cwd=plan.sd_cli.parent)
            hd_cut = home / f"02_hd_cutout_{kind}.png"
            cmd = [plan.hy_python, CUTOUT_SCRIPT, hd, hd_cut, "auto"]
            runner.run_cmd(f"texture-cutout-{kind}", [hd, plan.hy_python], [hd_cut], {}, cmd,
                           cwd=plan.hunyuan)
            project_views.append((kind, hd_cut))
        elif cut is not None:
            project_views.append((kind, cut))
    if not wants("game"):
        return finish(a, home, "Texture views: " + ", ".join(str(p) for _, p in project_views))

    # ---- game: retopo + bake ----------------------------------------------------
    game = home / "06_game.glb"
    G = cfg["retopo"]
    if G["enabled"]:
        cmd = blender_command(plan.blender, "retopo_bake.py", [
            "--input", painted, "--output", game, "--target-faces", G["target_faces"],
            "--method", G["method"], "--voxel-ratio", G["voxel_ratio"],
            "--texture-size", G["texture_size"], "--samples", G["bake_samples"],
            "--cage-ratio", G["cage_ratio"], "--device", G["device"], "--seed", seed,
            "--head-boost", G["head_boost"], "--image-format", G["image_format"],
            "--jpeg-quality", G["jpeg_quality"],
            "--stats", stats_dir / "game.json",
            *[arg for kind, path in project_views for arg in ("--view", f"{kind}={path}")]])
    else:
        cmd = build_finalize_command(plan.blender, FINALIZE_SCRIPT, painted, game,
                                     G["target_faces"] * 2)
    runner.run_cmd("game", [painted, *[p for _, p in project_views]], [game],
                   {"retopo": G, "seed": seed, "views": [k for k, _ in project_views]}, cmd)
    if not wants("rig"):
        return finish(a, home, f"Game mesh: {game}")

    # ---- rig --------------------------------------------------------------------
    rigged = home / "07_rigged.glb"
    if cfg["rig"]["enabled"]:
        args = ["--input", game, "--output", rigged, "--prefix", cfg["rig"]["bone_prefix"],
                "--image-format", G["image_format"], "--jpeg-quality", G["jpeg_quality"],
                "--stats", stats_dir / "rig.json"]
        if not cfg["rig"]["test_animation"]:
            args.append("--no-test-animation")
        cmd = blender_command(plan.blender, "rig.py", args)
        runner.run_cmd("rig", [game], [rigged], {"rig": cfg["rig"]}, cmd)
    if not wants("report"):
        return finish(a, home, f"Rigged: {rigged}")

    # ---- report -----------------------------------------------------------------
    Q = cfg["report"]
    targets = [("game", game)]
    if cfg["rig"]["enabled"]:
        targets.append(("rigged", rigged))
    for label, mesh in targets:
        args = ["--mesh", mesh, "--stats", stats_dir / f"quality_{label}.json",
                "--grid", Q["silhouette_grid"], "--preview-size", Q["preview_size"]]
        if front_cut.is_file() or (a.dry_run and cutouts):
            args += ["--cutout", front_cut]
        if Q["previews"]:
            args += ["--previews", home / "previews"]
        cmd = blender_command(plan.blender, "quality.py", args)
        runner.run_cmd(f"report-{label}", [mesh], [stats_dir / f"quality_{label}.json"], {"report": Q}, cmd)
    if a.dry_run:
        return finish(a, home, "")
    report = write_report(home, a, cfg, runner)
    lines = [f"Final: {rigged if cfg['rig']['enabled'] else game}",
             f"Report: {home / 'report.json'}", f"Gallery: {home / 'index.html'}"]
    lines += [f"WARNING: {w}" for w in report["warnings"]] or ["No warnings."]
    return finish(a, home, "\n".join(lines))


def finish(a, home: Path, message: str):
    if a.dry_run:
        print("\nDry run complete; nothing was generated.")
    elif message:
        print("\n" + message)
    return 0


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def warnings_for(stats: dict) -> list[str]:
    out = []
    q = stats.get("quality_game", {})
    iou = q.get("silhouette_iou")
    if iou is not None and iou < 0.80:
        out.append(f"silhouette match {iou:.2f} < 0.80: the shape does not follow the reference "
                   "outline; check views/cutouts and the shape stage")
    mesh = q.get("mesh", {})
    if mesh.get("pieces", 1) > 1:
        out.append(f"game mesh has {mesh['pieces']} separate pieces")
    if mesh.get("boundary_edges", 0) > 0:
        out.append(f"game mesh has holes ({mesh['boundary_edges']} open edges)")
    g = stats.get("game", {})
    if str(g.get("method", "")).startswith("decimate (quadriflow"):
        out.append("QuadriFlow failed; the game mesh was decimated instead (triangles, not quads)")
    if g.get("low_pieces") and g.get("shape_pieces") and g["low_pieces"] > g["shape_pieces"]:
        out.append(f"game mesh has {g['low_pieces']} pieces but the shape had "
                   f"{g['shape_pieces']}: a limb came loose")
    skipped = [v["view"] for v in g.get("projected_views", []) if v.get("skipped")]
    if skipped:
        out.append("views not projected (outline did not match the mesh): " + ", ".join(skipped)
                   + "; those sides keep the Paint3D colour")
    if (g.get("surface_error_max") or 0) > 0.03:
        out.append(f"low-poly mesh misses detail: max surface error {g['surface_error_max']:.3f} "
                   "of height; raise retopo.target_faces")
    r = stats.get("rig", {})
    if r:
        if r.get("unweighted_after_heat_fraction", 0) > 0.02:
            pct = round(100 * r["unweighted_after_heat_fraction"])
            out.append(f"automatic weights missed {pct}% of vertices (filled from the two "
                       "nearest bones); check the pose previews")
        sh = r.get("shoulder_height_fraction")
        if sh is not None and not 0.72 <= sh <= 0.9:
            out.append(f"shoulder joints placed at {sh:.2f} of the height (expected 0.72-0.90); "
                       "the arm bones are probably in the wrong place")
        hip = r.get("hip_height_fraction")
        if hip is not None and not 0.40 <= hip <= 0.62:
            out.append(f"hip joint placed at {hip:.2f} of the height (expected 0.40-0.62)")
        if (r.get("arm_leak") or 0) > 0.05:
            out.append(f"arm bones still move skin below the armpits (weight {r['arm_leak']}); "
                       "hips/flanks will distort when the arms move")
        if r.get("facing_detected", "").startswith("unknown"):
            out.append("could not tell which way the character faces; assumed -Y")
        if r.get("deform_bones_without_vertices"):
            out.append("bones without any skin: " + ", ".join(r["deform_bones_without_vertices"]))
    return out


def write_report(home: Path, a, cfg: dict, runner: Runner) -> dict:
    stats = {p.stem: _load(p) for p in sorted((home / "stats").glob("*.json"))}
    files = {}
    for name in ("01_reference.png", "02_cutout.png", "03_shape.glb", "05_painted.glb",
                 "06_game.glb", "07_rigged.glb", "07_rigged.blend"):
        if (home / name).is_file():
            files[name] = (home / name).stat().st_size
    for glb in ("06_game.glb", "07_rigged.glb"):
        if (home / glb).is_file():
            try:
                stats[f"glb_{glb}"] = readable_glb(home / glb, need_texture=True)
            except RuntimeError as exc:
                stats[f"glb_{glb}"] = {"error": str(exc)}
    report = {"asset": a.name, "settings": cfg, "files": files, "stats": stats,
              "warnings": warnings_for(stats), "timing": runner.timing}
    (home / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    write_gallery(home, report)
    return report


def write_gallery(home: Path, report: dict) -> None:
    imgs = [p for p in [home / "01_reference.png", *sorted(home.glob("01_view_*.png"))] if p.is_file()]
    imgs += sorted((home / "previews").glob("*.png")) if (home / "previews").is_dir() else []
    q = report["stats"].get("quality_game", {})
    rows = "".join(f"<li>{html.escape(w)}</li>" for w in report["warnings"]) or "<li>none</li>"
    cards = "".join(
        f'<figure><img src="{html.escape(str(p.relative_to(home)))}?v={int(p.stat().st_mtime)}">'
        f'<figcaption>'
        f"{html.escape(p.name)}</figcaption></figure>" for p in imgs)
    summary = {
        "silhouette match": q.get("silhouette_iou"),
        "game triangles": q.get("mesh", {}).get("triangles"),
        "pieces": q.get("mesh", {}).get("pieces"),
        "holes (open edges)": q.get("mesh", {}).get("boundary_edges"),
        "bones": report["stats"].get("rig", {}).get("bones"),
    }
    table = "".join(f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in summary.items())
    (home / "index.html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(report['asset'])} – AI3D</title>
<style>body{{font:15px system-ui;margin:24px;background:#1b1d21;color:#e6e6e6}}
figure{{display:inline-block;margin:6px;background:#26292f;padding:6px;border-radius:6px}}
img{{height:280px;display:block}}figcaption{{font-size:12px;color:#aaa}}
th{{text-align:left;padding-right:16px;color:#aaa}}li{{color:#f3c26b}}</style>
<h1>{html.escape(report['asset'])}</h1><table>{table}</table>
<h3>Warnings</h3><ul>{rows}</ul>{cards}
""")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
