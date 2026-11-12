"""Workable, non-destructive multi-part character assembly.

Uses ALL existing painted GLBs; imports each as an independent mesh hierarchy.
The old body/head preview is never overwritten. Initial placement is a bounds
heuristic, not automatic anatomical registration or collision correction.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from ai3d.characters.assembly import assemble_preview, validate_manifest
from ai3d.characters.autofit import fit_manifest
from ai3d.characters.card import load_card
from ai3d.output import run_directory

WORKABLE_VERSION = 1


def args_from_cli(argv=None):
    parser = argparse.ArgumentParser(description="Assemble existing standalone character GLBs")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refit", action="store_true",
                        help="Recalculate approximate placements, discarding manual adjustments")
    args = parser.parse_args(argv)
    if not args.prefix or not args.prefix[0].isalnum() or not all(
        c.isalnum() or c in "-_" for c in args.prefix
    ):
        parser.error("Invalid --prefix")
    if args.refit and args.dry_run:
        parser.error("Do not combine --refit and --dry-run")
    return args


def sources(card, prefix, output_dir):
    """Expected painted component paths in the card's stable order."""
    return {
        p["id"]: run_directory(f"{prefix}_{p['id']}_{p.get('reference_view') or 'front'}",
                               output_dir) / "05_painted.glb"
        for p in card["parts"]
    }


def use_prior_approved_head(manifest, prior_path):
    """Copy only the prior body/head placement and neck cuts, never source files."""
    if not prior_path.is_file():
        return False
    previous = json.loads(prior_path.read_text(encoding="utf-8"))
    if (previous.get("character_id") != manifest["character_id"] or
            previous.get("run_prefix") != manifest["run_prefix"]):
        return False
    old = {p["id"]: p for p in previous.get("parts", [])}
    fresh = {p["id"]: p for p in manifest["parts"]}
    if not all(ident in old and ident in fresh for ident in ("body", "head")):
        return False
    for ident in ("body", "head"):
        # Never transfer a manually adjusted transform to a different GLB.
        if Path(old[ident]["source"]).resolve() != Path(fresh[ident]["source"]).resolve():
            return False
    for ident in ("body", "head"):
        fresh[ident]["transform"] = deepcopy(old[ident]["transform"])
        fresh[ident]["cut"] = deepcopy(old[ident].get("cut", {"mode": "off"}))
        fresh[ident]["status"] = "reused_prior_body_head_fit"
    manifest["prior_body_head_assembly"] = str(prior_path)
    return True


def enable_workable_parts(manifest):
    for part in manifest["parts"]:
        part["visible"] = True
        part["include_in_preview"] = True
        if part["id"] not in ("body", "head"):
            part["status"] = "provisional_visible_unfitted"
    manifest["preview_layout"] = "overlay"
    manifest["workable_version"] = WORKABLE_VERSION
    manifest["workable_warnings"] = [
        "All configured independent painted meshes are included, even if they overlap.",
        "Generated gloves and clothing may include unwanted mannequin geometry.",
        "Bounds-only alignment is approximate; edit per-part transforms in assembly.json.",
        "No rigging, automatic skinning, garment shrinkwrap, weld, or topology repair.",
        "No source GLB or earlier body/head assembly is changed.",
    ]


def save_manifest(path, manifest):
    problems = validate_manifest(manifest, path.parent)
    if problems:
        raise RuntimeError("Invalid workable assembly: " + "; ".join(problems))
    fd, temporary = tempfile.mkstemp(prefix=".workable-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_scene(blender, output):
    renderer = Path(__file__).with_name("blender_render_component.py")
    if not renderer.is_file():
        raise RuntimeError("Missing Blender renderer: " + str(renderer))
    mesh = output / "preview.glb"
    if not mesh.is_file() or mesh.stat().st_size == 0:
        raise RuntimeError("Assembly did not export a non-empty preview.glb")
    command = [
        blender, "--background", "--factory-startup", "--python-exit-code", "1",
        "--python", str(renderer), "--",
        "--input", str(mesh), "--output-dir", str(output),
        "--part", "workable_character", "--force",
    ]
    print("[WORKABLE] Rendering four assembled views", flush=True)
    subprocess.run(command, check=True)
    for direction in ("front", "side", "back", "threequarter"):
        image = output / f"preview_{direction}.png"
        if not image.is_file() or image.stat().st_size == 0:
            raise RuntimeError("Missing assembled preview: " + str(image))


def assemble(args):
    card_path = args.card.expanduser().resolve()
    card = load_card(card_path)
    ids = [p["id"] for p in card["parts"]]
    if "body" not in ids or "head" not in ids:
        raise RuntimeError("Workable assembly requires body and head")
    output_root = args.output_dir.expanduser().resolve()
    source_paths = sources(card, args.prefix, output_root)
    target_name = args.prefix + "_workable_character"
    folder = run_directory(target_name, output_root)
    prior = run_directory(args.prefix + "_assembly", output_root) / "assembly.json"
    manifest_file = folder / "assembly.json"
    measures = folder / "measurements.json"

    print(f"\n[WORKABLE ASSEMBLY] {card['name']} | {len(ids)} independent parts")
    for ident, source in source_paths.items():
        ready = source.is_file() and source.stat().st_size > 0
        print(f"  {ident:<16} {'FOUND' if ready else 'MISSING'} {source}")
    print(f"Output: {folder}")
    print(f"Prior body/head alignment: {prior}")
    if args.dry_run:
        print("Dry run: no Blender, inference, changes or new files.")
        return folder

    missing = [str(p) for p in source_paths.values()
               if not p.is_file() or p.stat().st_size == 0]
    if missing:
        raise RuntimeError("Missing painted GLB(s); no assembly performed:\n  " +
                           "\n  ".join(missing))
    if not (shutil.which(args.blender) or Path(args.blender).is_file()):
        raise RuntimeError("Blender executable not found: " + args.blender)
    if folder.is_symlink() or manifest_file.is_symlink():
        raise RuntimeError("Refusing symlink output or manifest")

    if not manifest_file.exists():
        # Initial geometry measurement includes every unmodified part, staged
        # separately. This is a NEW folder, not the approved head/body preview.
        print("[WORKABLE] Import and measure all standalone meshes", flush=True)
        assemble_preview(card_path, name=target_name, run_prefix=args.prefix,
                         output_root=output_root, blender=args.blender,
                         layout="overlay", include_all_parts=True,
                         source_stage="painted")
    if not measures.is_file():
        assemble_preview(card_path, name=target_name, run_prefix=args.prefix,
                         output_root=output_root, blender=args.blender, rebuild=True)
    if not manifest_file.is_file():
        raise RuntimeError("Missing assembly manifest after Blender import")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (manifest.get("character_id") != card["id"] or
            manifest.get("run_prefix") != args.prefix):
        raise RuntimeError("Existing workable folder belongs to another run")
    previous_ids = [part["id"] for part in manifest.get("parts", [])]
    if previous_ids != ids:
        raise RuntimeError("Part inventory changed; choose a new --prefix to avoid clobbering edits")

    initial = manifest.get("workable_version") != WORKABLE_VERSION
    if initial or args.refit:
        fit_manifest(manifest_file, measures, refit=args.refit)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if use_prior_approved_head(manifest, prior):
            print("[WORKABLE] Preserved prior body/head alignment and cuts")
        else:
            print("[WORKABLE] No matching prior body/head fit; using bounds estimate")
        enable_workable_parts(manifest)
        save_manifest(manifest_file, manifest)
    else:
        print("[WORKABLE] Preserving previously edited transforms and visibility")

    print("[WORKABLE] Exporting editable scene with configured parts", flush=True)
    assemble_preview(card_path, name=target_name, run_prefix=args.prefix,
                     output_root=output_root, blender=args.blender, rebuild=True)
    render_scene(args.blender, folder)
    print("\n[WORKABLE] Complete:", folder)
    print("Blender:", folder / "preview.blend")
    print("GLB:", folder / "preview.glb")
    print("Transforms:", manifest_file)
    print("Renders:", folder / "preview_front.png", "(+ side/back/threequarter)")
    print("All placements are provisional; inspect in Blender before calling it game-ready.")
    return folder


def main(argv=None):
    try:
        assemble(args_from_cli(argv))
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
