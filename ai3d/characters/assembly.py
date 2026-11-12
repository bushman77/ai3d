"""Non-destructive Blender assembly preview for character-card components.

This is deliberately a *comparison and fitting workspace*, not an automatic
body-part replacement, mesh join, rig, or production game export.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

from ai3d.assembly.cutting import default_cut, validate_cut
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
    include_all_parts: bool = False,
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
    selection = [base, attach]
    if include_all_parts:
        selection.extend(part["id"] for part in card["parts"] if part["id"] not in selection)
    for part_id in selection:
        part = _part(card, part_id)
        active = part_id in (base, attach)
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
            "status": "unfitted" if active else "staged_unfitted",
            "visible": active,
            "include_in_preview": active,
            "cut": default_cut(keep="below" if part_id == base else "above"),
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
            "Regions and accessories are staged but hidden until fitted, to avoid duplicate body geometry.",
            "Cut-plane operations are off by default; guide and apply modes are opt-in.",
            "No automatic head alignment, neck seam welding, joining, or rigging.",
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
    # The upper-garment replacement is a separate optional Blender working
    # pass. Never silently enable a destructive-on-copy geometry operation.
    coverage = manifest.get("clothing_replacement")
    if coverage is not None:
        if not isinstance(coverage, dict) or coverage.get("mode") not in (
            "off", "upper_coverage_v1",
        ):
            errors.append("clothing_replacement.mode must be off or upper_coverage_v1")
        elif coverage["mode"] == "upper_coverage_v1":
            if manifest.get("preview_layout") != "overlay":
                errors.append("upper clothing replacement requires overlay layout")
            values = {}
            for key in ("min_height_ratio", "max_height_ratio",
                        "max_distance_ratio", "max_removed_fraction"):
                value = coverage.get(key)
                if (type(value) not in (float, int) or
                        not math.isfinite(value) or not 0 < value < 1):
                    errors.append(f"clothing_replacement.{key} must be finite and between 0 and 1")
                else:
                    values[key] = value
            if ("min_height_ratio" in values and "max_height_ratio" in values
                    and values["min_height_ratio"] >= values["max_height_ratio"]):
                errors.append("clothing_replacement height ratios must increase")
    parts = manifest.get("parts")
    if isinstance(coverage, dict) and coverage.get("mode") == "upper_coverage_v1":
        ids = {part.get("id") for part in parts if isinstance(part, dict)} if isinstance(parts, list) else set()
        if not {"body", "upper_outfit"}.issubset(ids):
            errors.append("upper clothing replacement requires body and upper_outfit")
    if not isinstance(parts, list) or len(parts) < 2:
        errors.append("parts must contain at least two components")
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
            for flag in ("visible", "include_in_preview"):
                if flag in part and type(part[flag]) is not bool:
                    errors.append(f"{label}.{flag} must be a boolean")
            if not isinstance(part.get("source"), str) or not part["source"]:
                errors.append(f"{label}.source must be an existing GLB path")
            transform = part.get("transform")
            if not isinstance(transform, dict):
                errors.append(f"{label}.transform must be an object")
                continue
            # Old v1 assembly manifests remain valid without a cut section;
            # a user may add the section via 'character cut' later.
            if "cut" in part:
                errors.extend(validate_cut(part["cut"], f"{label}.cut"))
            # Optional anatomical glove-pair layout is generated by autofit
            # and consumed only by the Blender working-copy assembler.
            if "pair_layout" in part:
                layout = part["pair_layout"]
                if part_id != "hands" or not isinstance(layout, dict) or (
                    layout.get("mode") != "split_x_to_wrists_v1"
                ):
                    errors.append(f"{label}.pair_layout must describe a hands split")
                else:
                    for key in ("left_wrist", "right_wrist"):
                        vec = layout.get(key)
                        if (not isinstance(vec, list) or len(vec) != 3 or
                                any(type(x) not in (int, float) or
                                    not math.isfinite(x) for x in vec)):
                            errors.append(f"{label}.pair_layout.{key} requires 3 finite coordinates")
                    for key in ("hand_length", "hand_width"):
                        value = layout.get(key)
                        if (type(value) not in (int, float) or
                                not math.isfinite(value) or value <= 1e-6):
                            errors.append(f"{label}.pair_layout.{key} must be positive and finite")
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
    include_all_parts: bool = False,
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
            source_stage=source_stage, layout=layout,
            include_all_parts=include_all_parts, output_root=output_root,
        )
    problems = validate_manifest(manifest, folder)
    if problems:
        raise RuntimeError("Invalid assembly manifest:\n  - " + "\n  - ".join(problems))
    print(f"Assembly: {card['name']} | layout: {manifest['preview_layout']}")
    print(f"Output: {folder}")
    for part in manifest["parts"]:
        present = "FOUND" if Path(part["source"]).is_file() else "MISSING"
        cut = part.get("cut", {})
        print(f"  {part['id']}: {part['source']} [{present}]; cut={cut.get('mode', 'off')}; "
              f"visible={part.get('visible', True)}; export={part.get('include_in_preview', True)}")
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
    print("Original component GLBs unchanged. Guide/apply mode affects assembly copies only.")
    print("No automatic fitting, joining, neck seam welding, or rigging performed.")
    return manifest


def configure_cut(
    manifest_path: Path, *,
    part_id: str,
    mode: str,
    plane_z: float | None = None,
    keep: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Edit one assembly manifest's cut settings, never running Blender.

    Previous v1 manifests without cut keys are supported. This is explicitly
    separate from --rebuild, so editing a guide never accidentally applies a
    destructive operation. The only mutated file is the assembly manifest.
    """
    manifest_path = Path(manifest_path).expanduser()
    if manifest_path.name != "assembly.json" or manifest_path.is_symlink():
        raise RuntimeError("Expected a regular assembly.json file")
    if not manifest_path.is_file():
        raise RuntimeError(f"Assembly manifest not found: {manifest_path}")
    folder = manifest_path.parent.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matching = [p for p in manifest.get("parts", []) if p.get("id") == part_id]
    if len(matching) != 1:
        raise RuntimeError(f"Assembly has no unique component {part_id!r}")
    part = matching[0]
    cut = dict(part.get("cut") or default_cut(
        keep="below" if part_id == manifest.get("base_part") else "above"
    ))
    if mode not in ("off", "guide", "apply"):
        raise RuntimeError("--mode must be off, guide, or apply")
    if mode != "off" and plane_z is None:
        raise RuntimeError("For guide/apply, specify an explicit --z plane height")
    cut["mode"] = mode
    if plane_z is not None:
        cut["plane_z"] = plane_z
    if keep is not None:
        cut["keep"] = keep
    cut.setdefault("show_guide", True)
    part["cut"] = cut
    errors = validate_manifest(manifest, folder)
    if errors:
        raise RuntimeError("Invalid cut configuration:\n  - " + "\n  - ".join(errors))
    print(
        f"Cut for {part_id}: mode={cut['mode']}, "
        f"world Z={cut['plane_z']}, keep={cut['keep']}"
    )
    if dry_run:
        print("Dry run; existing assembly.json unchanged.")
        return manifest

    # A short-lived temporary file in the same folder makes replacement
    # atomic, and preserves the original on validation/serialization errors.
    fd, temp = tempfile.mkstemp(prefix=".assembly-cut-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2, allow_nan=False)
            file.write("\n")
        os.replace(temp, manifest_path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("Updated manifest. Run 'character assemble ... --rebuild' to see the result.")
    return manifest

def stage_components(
    manifest_path: Path,
    card_path: Path,
    *,
    part_ids: list[str] | None = None,
    all_parts: bool = False,
    dry_run: bool = False,
) -> dict:
    """Stage additional generated components in an existing assembly.

    Do not reset head fitting, existing cuts, or the assembly's original
    GLB references. Newly staged meshes are hidden and excluded from the
    preview GLB, because region models often duplicate original geometry.
    """
    manifest_path = Path(manifest_path).expanduser()
    if manifest_path.name != "assembly.json" or manifest_path.is_symlink():
        raise RuntimeError("Expected a regular assembly.json")
    if not manifest_path.is_file():
        raise RuntimeError(f"Assembly manifest not found: {manifest_path}")
    card = load_card(Path(card_path).expanduser())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("character_id") != card["id"]:
        raise RuntimeError("Assembly belongs to a different character card")
    if all_parts == bool(part_ids):
        raise RuntimeError("Select either --all or at least one --part")
    existing = {part["id"] for part in manifest["parts"]}
    target = ({p["id"] for p in card["parts"]} if all_parts else set(part_ids))
    missing = target - {p["id"] for p in card["parts"]}
    if missing:
        raise RuntimeError("Unknown character parts: " + ", ".join(sorted(missing)))
    new_parts = [p for p in card["parts"] if p["id"] in target and p["id"] not in existing]
    if not new_parts:
        print("All requested parts are already staged; nothing changed.")
        return manifest
    folder = manifest_path.parent.resolve()
    root = folder.parent
    for part in new_parts:
        view = part.get("reference_view") or "front"
        run_name = f"{manifest['run_prefix']}_{part['id']}_{view}"
        source = run_directory(run_name, root) / FILE_BY_STAGE[manifest["source_stage"]]
        state = "FOUND" if source.is_file() and source.stat().st_size > 0 else "MISSING"
        print(f"  Stage {part['id']}: {source} [{state}] (hidden, excluded from GLB)")
        if not dry_run and state == "MISSING":
            raise RuntimeError(f"Missing component GLB: {source}")
        manifest["parts"].append({
            "id": part["id"],
            "label": part["label"],
            "card_kind": part["kind"],
            "source": str(source),
            "parent_part": part.get("parent"),
            "intended_attachment": part.get("attachment"),
            "status": "staged_unfitted",
            "visible": False,
            "include_in_preview": False,
            "cut": default_cut(keep="above"),
            "transform": {
                "position": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
        })
    errors = validate_manifest(manifest, folder)
    if errors:
        raise RuntimeError("Invalid staged assembly:\n  - " + "\n  - ".join(errors))
    if dry_run:
        print("Dry run: assembly.json unchanged.")
        return manifest
    # Atomic replace without opening/overwriting any generated GLBs.
    fd, temp = tempfile.mkstemp(prefix=".assembly-stage-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temp, manifest_path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("Staged components in assembly.json. Run 'character assemble ... --rebuild'.")
    return manifest


def set_component_visibility(
    manifest_path: Path,
    *,
    part_id: str,
    visible: bool | None = None,
    include_in_preview: bool | None = None,
    dry_run: bool = False,
) -> dict:
    """Opt a staged component in/out of the Blender view and comparison GLB."""
    manifest_path = Path(manifest_path).expanduser()
    if manifest_path.name != "assembly.json" or manifest_path.is_symlink():
        raise RuntimeError("Expected a regular assembly.json")
    if not manifest_path.is_file():
        raise RuntimeError(f"Assembly manifest not found: {manifest_path}")
    if visible is None and include_in_preview is None:
        raise RuntimeError("Specify --show/--hide or --export/--no-export")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [part for part in manifest.get("parts", []) if part.get("id") == part_id]
    if len(matches) != 1:
        raise RuntimeError(f"Unknown or ambiguous component: {part_id}")
    part = matches[0]
    if visible is not None:
        part["visible"] = visible
    if include_in_preview is not None:
        part["include_in_preview"] = include_in_preview
    errors = validate_manifest(manifest, manifest_path.parent.resolve())
    if errors:
        raise RuntimeError("Invalid component settings:\n  - " + "\n  - ".join(errors))
    print(f"Component {part_id}: visible={part.get('visible', True)}, "
          f"include_in_preview={part.get('include_in_preview', True)}")
    if dry_run:
        return manifest
    fd, temp = tempfile.mkstemp(prefix=".assembly-component-", suffix=".tmp",
                                dir=manifest_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temp, manifest_path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return manifest
