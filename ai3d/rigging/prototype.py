"""CLI runner for a first, *unskinned* Blender humanoid rig prototype.

Copy the existing manually fitted assembly .blend into a separate rigging run.
Do not regenerate meshes, edit assembly.json, or overwrite existing rig tests.
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
import tempfile

from ai3d.characters.card import load_card
from ai3d.output import run_directory

BLENDER_SCRIPT = Path(__file__).with_name("blender_prototype.py")
VERIFY_SCRIPT = Path(__file__).with_name("blender_verify.py")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def options(argv=None):
    parser = argparse.ArgumentParser(description="Build a skeleton-only Blender prototype")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--assembly", default=None,
                        help="Existing assembled run directory name (default PREFIX_workable_character)")
    parser.add_argument("--source-blend", type=Path,
                        help="Use this exact existing, manually edited .blend file as read-only rig source")
    parser.add_argument("--rig-name",
                        help="Separate rig output directory name (default PREFIX_rig_prototype)")
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--force", action="store_true",
                        help="Explicitly replace the existing rig prototype (not the source assembly)")
    parser.add_argument("--dry-run", action="store_true")
    opts = parser.parse_args(argv)

    if opts.source_blend is not None and opts.assembly is not None:
        parser.error("Use --source-blend OR --assembly, not both")
    for label, value in [
        ("prefix", opts.prefix),
        ("assembly", opts.assembly),
        ("rig-name", opts.rig_name),
    ]:
        if value is not None and not SAFE_NAME.fullmatch(value):
            parser.error(f"Invalid --{label}: must be a safe output directory name")
    if opts.dry_run and opts.force:
        parser.error("--force and --dry-run cannot be combined")
    return opts


def plan_paths(opts):
    root = opts.output_dir.expanduser().resolve()
    input_name = opts.assembly or f"{opts.prefix}_workable_character"
    output_name = opts.rig_name or f"{opts.prefix}_rig_prototype"
    source_folder = run_directory(input_name, root)
    source_file = (
        opts.source_blend.expanduser().resolve()
        if opts.source_blend is not None
        else source_folder / "preview.blend"
    )
    target_folder = run_directory(output_name, root)
    if source_file.parent == target_folder or source_file == target_folder / "rig_prototype.blend":
        raise RuntimeError("Rig output directory cannot be the source scene directory")
    if source_file.suffix.lower() != ".blend":
        raise RuntimeError("Rig source must be a .blend file")
    return {
        "assembly_folder": source_file.parent,
        "assembly_blend": source_file,
        "assembly_manifest": source_folder / "assembly.json"
            if opts.source_blend is None else None,
        "target_folder": target_folder,
        "rig_blend": target_folder / "rig_prototype.blend",
        "report": target_folder / "skeleton.json",
    }


def build(opts):
    card = load_card(opts.card.expanduser().resolve(strict=True))
    paths = plan_paths(opts)

    print(f"\n[RIG PROTOTYPE] {card['name']} | prefix={opts.prefix}", flush=True)
    print("Source (read-only):", paths["assembly_blend"], flush=True)
    print("Output Blender scene:", paths["rig_blend"], flush=True)
    print("Output joint report:", paths["report"], flush=True)

    if opts.dry_run:
        print("Dry run: no Blender launched, no models regenerated, no files written.", flush=True)
        return paths

    manifest_file = paths["assembly_manifest"]
    scene_file = paths["assembly_blend"]
    if manifest_file is not None:
        if not manifest_file.is_file():
            raise RuntimeError("Missing existing assembly manifest: " + str(manifest_file))
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest.get("character_id") != card["id"] or manifest.get("run_prefix") != opts.prefix:
            raise RuntimeError("Existing assembly does not match the selected character/prefix")
        if manifest.get("preview_layout") != "overlay":
            raise RuntimeError("Rigging requires an already fitted overlay assembly")
        if "body" not in {p.get("id") for p in manifest.get("parts", [])}:
            raise RuntimeError("Rigging requires a body component")
    # An explicitly supplied manual scene is the source of truth. Do not
    # rebuild from the assembly manifest or import the earlier component GLBs.
    # Blender itself verifies the required AI3D body hierarchy/character meshes.
    if not scene_file.is_file() or scene_file.stat().st_size == 0:
        raise RuntimeError("Missing or empty source Blender file: " + str(scene_file))
    if not BLENDER_SCRIPT.is_file() or not VERIFY_SCRIPT.is_file():
        raise RuntimeError("Missing Blender rig prototype or validation implementation")
    blender = shutil.which(opts.blender)
    if blender is None:
        candidate = Path(opts.blender).expanduser()
        if not candidate.is_file():
            raise RuntimeError("Blender executable not found: " + opts.blender)
        blender = str(candidate)

    folder = paths["target_folder"]
    if folder.is_symlink():
        raise RuntimeError("Refusing symlink rig output directory: " + str(folder))
    if folder.exists() and not folder.is_dir():
        raise RuntimeError("Rig output location is not a directory: " + str(folder))
    if folder.is_dir() and any(folder.iterdir()) and not opts.force:
        raise RuntimeError("Rig output directory already exists and contains files; choose a new --rig-name")
    for name in ("rig_blend", "report"):
        if paths[name].is_symlink():
            raise RuntimeError("Refusing symlink rig output: " + str(paths[name]))
    if any(paths[name].exists() for name in ("rig_blend", "report")) and not opts.force:
        raise RuntimeError("Rig prototype already exists; inspect it before using --force")

    folder.mkdir(parents=True, exist_ok=True)
    # Save to scratch paths and publish only after both Blender files validate;
    # a failed Blender run will not replace an earlier prototype.
    with tempfile.TemporaryDirectory(prefix=".rig-build-", dir=folder) as temporary:
        scratch = Path(temporary)
        blend = scratch / "rig_prototype.blend"
        report = scratch / "skeleton.json"
        command = [
            blender, "--background", "--factory-startup", str(scene_file),
            "--python-exit-code", "1", "--python", str(BLENDER_SCRIPT), "--",
            "--source", str(scene_file),
            "--output", str(blend),
            "--report", str(report),
        ]
        print("[RIG PROTOTYPE] Building bones in Blender", flush=True)
        subprocess.run(command, check=True)
        for expected in (blend, report):
            if not expected.is_file() or expected.stat().st_size == 0:
                raise RuntimeError("Blender did not create " + str(expected))
        skeleton = json.loads(report.read_text(encoding="utf-8"))
        if not skeleton.get("bones") or skeleton.get("skinned") is not False:
            raise RuntimeError("Unexpected rig prototype report")
        if len(skeleton.get("component_objects", [])) < 2:
            raise RuntimeError("Rig report does not confirm Mara's character meshes")
        # Reopen the Blender output in a new process and inspect real objects.
        # The previous implementation only tested that a .blend file existed.
        verify = [
            blender, "--background", "--factory-startup", str(blend),
            "--python-exit-code", "1", "--python", str(VERIFY_SCRIPT), "--",
            "--blend", str(blend), "--report", str(report),
        ]
        print("[RIG PROTOTYPE] Reopening saved Blender file for verification", flush=True)
        subprocess.run(verify, check=True)
        os.replace(blend, paths["rig_blend"])
        os.replace(report, paths["report"])

    print(f"[RIG PROTOTYPE] Created {len(skeleton['bones'])} editable bones", flush=True)
    print("[RIG PROTOTYPE] No mesh weights, rig export or animations were generated.", flush=True)
    return paths


def main(argv=None):
    try:
        build(options(argv))
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
