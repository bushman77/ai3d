"""Non-destructive Blender assembly preview for character-card components.

This is deliberately a *comparison and fitting workspace*, not an automatic
body-part replacement, mesh join, rig, or production game export.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil

from ai3d.characters.card import load_card
from ai3d.export.validation import readable_glb
from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory
from ai3d.pipeline_runner import Runner

FILE_BY_STAGE = {"painted": "05_painted.glb", "game": "06_game.glb"}
LAYOUTS = ("side_by_side", "overlay")
MANIFEST_VERSION = 1
SCRIPT = Path(__file__).with_name("blender_assembly_preview.py")


def _part(card: dict, part_id: str) -> dict:
    parts = {p["id"]: p for p in card["parts"]}
    if part_id not in parts:
        raise RuntimeError(
            f"Unknown part {part_id!r}; available: {', '.join(parts)}"
        )
    return parts[part_id]


def build_assembly_plan(
    card: dict, *,
    run_prefix: str,
    name: str,
    base: str = "body",
    attach: str = "head",
    source_stage: str = "painted",
    layout: str = "side_by_side",
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict:
    """Return a side-effect-free manifest describing two existing GLB sources."""
    if base == attach:
        raise RuntimeError("--base and --attach must be distinct")
    if source_stage not in FILE_BY_STAGE:
        raise RuntimeError(f"Unsupported source stage: {source_stage}")
    if layout not in LAYOUTS:
        raise RuntimeError(f"Unsupported preview layout: {layout}")
    output = run_directory(name, output_root)
    components = []
    for part_id in (base, attach):
        part = _part(card, part_id)
        view = part.get("reference_view") or "front"
        asset = run_directory(f"{run_prefix}_{part_id}_{view}", output_root)
        glb = asset / FILE_BY_STAGE[source_stage]
        components.append({
            "id": part_id,
            "label": part["label"],
            "card_kind": part["kind"],
            "source": str(glb),
            "parent_part": None if part_id == base else base,
            "intended_attachment": part.get("attachment"),
            "status": "unfitted",
            "transform": {
                "position": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
        })
    return {
        "manifest_version": MANIFEST_VERSION,
        "character_id": card["id"],
        "character_name": card["name"],
        "card_revision": card["revision"],
        "source_stage": source_stage,
        "run_prefix": run_prefix,
        "preview_layout": layout,
        "base_part": base,
        "parts": components,
        "units": card["assembly"]["units"],
        "up_axis": card["assembly"]["up_axis"],
        "forward_axis": card["assembly"]["forward_axis"],
        "output": {
            "blend": str(output / "preview.blend"),
            "glb": str(output / "preview.glb"),
            "measurements": str(output / "measurements.json"),
        },
        "notes": [
            "This is a non-destructive comparison of independent meshes.",
            "The head is NOT cut into the body, aligned, joined, or rigged.",
            "side_by_side applies a temporary display offset, recorded in measurements.json.",
            "Edit parts[*].transform, switch preview_layout to overlay, then use --rebuild.",
            "preview.glb is NOT a production assembled character asset.",
        ],
    }


def validate_manifest(manifest: object, output: Path) -> list[str]:
    """Validate editable transforms and constrain outputs to this assembly run."""
    errors = []
    if not isinstance(manifest, dict):
        return ["assembly manifest must be an object"]
    if type(manifest.get("manifest_version")) is not int or manifest["manifest_version"] != 1:
        errors.append("manifest_version must be 1")
    if manifest.get("preview_layout") not in LAYOUTS:
        errors.append("preview_layout must be side_by_side or overlay")
    parts = manifest.get("parts")
    if not isinstance(parts, list) or len(parts) != 2:
        errors.append("parts must contain exactly two components")
    else:
        seen = set()
        for i, part in enumerate(parts):
            label = f"parts[{i}]"
            if not isinstance(part, dict):
                errors.append(f"{label} must be an object")
                continue
            part_id = part.get("id")
            if not isinstance(part_id, str) or not part_id or part_id in seen:
                errors.append(f"{label}.id must be distinct and nonempty")
            else:
                seen.add(part_id)
            if not isinstance(part.get("source"), str) or not part["source"]:
                errors.append(f"{label}.source must be an existing GLB path")
            transform = part.get("transform")
            if not isinstance(transform, dict):
                errors.append(f"{label}.transform must be an object")
                continue
            for key in ("position", "rotation_deg", "scale"):
                vec = transform.get(key)
                if (not isinstance(vec, list) or len(vec) != 3 or
                        any(type(x) not in (int, float) or
                            not math.isfinite(x) for x in vec)):
                    errors.append(f"{label}.transform.{key} must be three finite numbers")
                elif key == "scale" and any(x <= 0 for x in vec):
                    errors.append(f"{label}.transform.scale values must be positive")
    outputs = manifest.get("output")
    if not isinstance(outputs, dict):
        errors.append("output must be an object")
    else:
        for key, filename in (
            ("blend", "preview.blend"),
            ("glb", "preview.glb"),
            ("measurements", "measurements.json"),
        ):
            path = outputs.get(key)
            if not isinstance(path, str) or Path(path).resolve() != output / filename:
                errors.append(f"output.{key} must point to {output / filename}")
    return errors


def build_blender_command(blender: str, script: Path, manifest: Path) -> list[str]:
    """Avoid shell interpolation, with Blender nonzero exit on Python errors."""
    return [
        blender, "--background", "--factory-startup",
        "--python-exit-code", "1", "--python", str(script),
        "--", "--manifest", str(manifest),
    ]


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def assemble_preview(
    card_path: Path, *,
    name: str,
    run_prefix: str,
    base: str = "body",
    attach: str = "head",
    source_stage: str = "painted",
    layout: str = "side_by_side",
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    blender: str = "blender",
    dry_run: bool = False,
    rebuild: bool = False,
) -> dict:
    """Create or explicitly rebuild an editable Blender comparison scene."""
    card_path = Path(card_path).expanduser().resolve()
    card = load_card(card_path)
    folder = run_directory(name, output_root)
    manifest_path = folder / "assembly.json"
    if folder.is_symlink():
        raise RuntimeError(f"Refusing assembly output symlink: {folder}")
    if folder.exists() and not folder.is_dir():
        raise RuntimeError(f"Assembly output exists but is not a directory: {folder}")
    for candidate in (
        manifest_path, folder / "preview.blend", folder / "preview.glb",
        folder / "measurements.json", folder / "logs", folder / ".stages",
    ):
        if candidate.is_symlink():
            raise RuntimeError(f"Refusing assembly output symlink: {candidate}")

    if rebuild:
        if not manifest_path.is_file():
            raise RuntimeError(f"--rebuild requires an existing assembly manifest: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise RuntimeError(f"Cannot read assembly manifest: {exc}") from exc
        if manifest.get("character_id") != card["id"]:
            raise RuntimeError("Existing assembly manifest belongs to another character")
    else:
        if folder.exists():
            raise RuntimeError(
                f"Assembly run already exists: {folder}; choose a new --name "
                "or use --rebuild with the existing assembly.json"
            )
        manifest = build_assembly_plan(
            card, name=name, run_prefix=run_prefix, base=base, attach=attach,
            source_stage=source_stage, layout=layout, output_root=output_root,
        )
    problems = validate_manifest(manifest, folder)
    if problems:
        raise RuntimeError("Invalid assembly manifest:\n  - " + "\n  - ".join(problems))
    print(f"Assembly: {card['name']} | layout: {manifest['preview_layout']}")
    print(f"Output: {folder}")
    for part in manifest["parts"]:
        present = "FOUND" if Path(part["source"]).is_file() else "MISSING"
        print(f"  {part['id']}: {part['source']} [{present}]")
    if dry_run:
        print("Dry run: no Blender process and no output files created.")
        return manifest

    for part in manifest["parts"]:
        path = Path(part["source"])
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing or empty source GLB for {part['id']}: {path}")
        readable_glb(path, need_texture=True)

    executable = shutil.which(blender)
    if executable is None:
        chosen = Path(blender).expanduser()
        if not chosen.is_file():
            raise RuntimeError(f"Cannot locate Blender executable: {blender}")
        executable = str(chosen)
    if not SCRIPT.is_file():
        raise RuntimeError(f"Missing Blender preview script: {SCRIPT}")
    # Add source fingerprints to a newly created manifest, keeping edits
    # to transforms and layout on an explicit --rebuild.
    if not rebuild:
        manifest["source_sha256"] = {
            p["id"]: _hash(Path(p["source"])) for p in manifest["parts"]
        }
    folder.mkdir(parents=True, exist_ok=True)
    if not rebuild:
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")

    runner = Runner(folder, resume=False, force=rebuild, dry=False)
    command = build_blender_command(executable, SCRIPT, manifest_path)
    runner.command("assembly-preview", command)
    for key, path in manifest["output"].items():
        output_file = Path(path)
        if not output_file.is_file() or output_file.stat().st_size == 0:
            raise RuntimeError(f"Blender did not produce {key}: {output_file}")
    print("Preview Blender scene: " + manifest["output"]["blend"])
    print("Preview multi-object GLB: " + manifest["output"]["glb"])
    print("Measurements: " + manifest["output"]["measurements"])
    print("Original components unchanged. No fitting, cutting, joining or rigging performed.")
    return manifest
