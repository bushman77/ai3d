"""Build and render every character-card component as an independent 3D prototype.

Unlike the normal reference-only batch mode, this explicitly enables region
meshes. Each part is generated sequentially to accommodate a 6 GB GPU.
Existing painted meshes are preserved unless --force is given.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from ai3d.characters.card import ROOT, load_card
from ai3d.output import run_directory


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Render standalone 3D models for every card part")
    parser.add_argument("--card", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--quality", default="fast",
                        choices=("fast", "low", "medium", "high", "highest"))
    parser.add_argument("--part", action="append", default=[])
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--paint-debug", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.prefix or not args.prefix[0].isalnum() or not all(
        c.isalnum() or c in "_-" for c in args.prefix
    ):
        parser.error("invalid --prefix")
    if args.force and args.dry_run:
        parser.error("use either --force or --dry-run")
    return args


def run(args):
    card = load_card(args.card)
    known = {p["id"]: p for p in card["parts"]}
    chosen = list(dict.fromkeys(args.part)) if args.part else list(known)
    for part_id in chosen:
        if part_id not in known:
            raise RuntimeError(
                f"Unknown part {part_id!r}; available: {', '.join(known)}"
            )
    script = ROOT / "ai3d/characters/blender_render_component.py"
    if not script.is_file():
        raise RuntimeError("Missing Blender component renderer: " + str(script))
    if not args.dry_run and not (shutil.which(args.blender) or Path(args.blender).is_file()):
        raise RuntimeError("Blender executable not found: " + args.blender)

    out = args.output_dir.expanduser().resolve()
    print(f"\n[STANDALONE 3D PROTOTYPES] {card['name']} | prefix={args.prefix}")
    print("Selected:", ", ".join(chosen))
    print("All components produce separate GLBs and front/side/back/threequarter renders.")
    print("Region meshes are experimental: not trimmed, fitted, rigged, or assembled.", flush=True)
    for index, part_id in enumerate(chosen, 1):
        part = known[part_id]
        view = part.get("reference_view") or "front"
        name = f"{args.prefix}_{part_id}_{view}"
        directory = run_directory(name, out)
        painted = directory / "05_painted.glb"
        available = painted.is_file() and painted.stat().st_size > 0
        print(f"\n[COMPONENT {index}/{len(chosen)}] {part_id}: {painted}", flush=True)
        if args.render_only:
            if not available and not args.dry_run:
                raise RuntimeError("Missing painted mesh for --render-only: " + str(painted))
            print("Reusing existing mesh (render only).", flush=True)
        elif available and not args.force:
            # Do not re-run a successful body/head when the source card changes:
            # this would otherwise invalidate an older Qwen cache stamp.
            print("Preserving existing painted component.", flush=True)
        else:
            command = [
                sys.executable, "-m", "ai3d", "character", "generate",
                str(args.card), "--part", part_id, "--include-regions",
                "--stop-after", "paint", "--run-prefix", args.prefix,
                "--output-dir", str(out), "--blender", args.blender,
                "--quality", args.quality,
                "--force" if args.force else "--resume",
            ]
            if args.paint_debug:
                command.append("--paint-debug")
            if args.dry_run:
                command.append("--dry-run")
            print("Generate:", shlex.join(command), flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
        if not args.dry_run and (not painted.is_file() or painted.stat().st_size == 0):
            raise RuntimeError("Missing painted GLB after processing: " + str(painted))
        render = [
            args.blender, "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(script), "--",
            "--input", str(painted), "--output-dir", str(directory),
            "--part", part_id,
        ]
        if args.force:
            render.append("--force")
        if args.dry_run:
            print("[DRY RUN] Would render:", shlex.join(render), flush=True)
        else:
            print("Render:", shlex.join(render), flush=True)
            subprocess.run(render, cwd=ROOT, check=True)

    gallery = [
        sys.executable, "-m", "ai3d.characters.prototype_gallery",
        "--card", str(args.card), "--prefix", args.prefix,
        "--output-dir", str(out),
    ]
    for part_id in chosen:
        gallery.extend(["--part", part_id])
    if args.dry_run:
        print("[DRY RUN] Would create gallery:", shlex.join(gallery))
    else:
        subprocess.run(gallery, cwd=ROOT, check=True)
        print("\nDONE. Open: " + str(out / (args.prefix + "_prototypes") / "index.html"))


def main(argv=None):
    try:
        run(parse_args(argv))
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
