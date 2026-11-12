"""Workable, non-destructive multi-part character assembly.

Uses ALL existing painted GLBs; imports each as an independent mesh hierarchy.
The old body/head preview is never overwritten. Placement uses explicit
anatomical fraction targets inferred from body bounds and a Blender glove-pair
split; it is not joint tracking, garment registration or collision correction.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from html import escape
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
UPPER_REPLACEMENT_MODE = "upper_coverage_v1"


def upper_replacement_plan():
    """Conservative default mask: torso and sleeves, never head/legs/hands."""
    return {
        "mode": UPPER_REPLACEMENT_MODE,
        "min_height_ratio": 0.49,
        "max_height_ratio": 0.93,
        "max_distance_ratio": 0.065,
        "max_removed_fraction": 0.55,
    }



def args_from_cli(argv=None):
    parser = argparse.ArgumentParser(description="Assemble existing standalone character GLBs")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--name", help="Distinct assembly output directory (default: PREFIX_workable_character)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-upper-body", action="store_true",
                        help="On a new assembly, mask body faces covered by the upper garment (copies only)")
    parser.add_argument("--refit", action="store_true",
                        help="Recalculate approximate placements, discarding manual adjustments")
    args = parser.parse_args(argv)
    if not args.prefix or not args.prefix[0].isalnum() or not all(
        c.isalnum() or c in "-_" for c in args.prefix
    ):
        parser.error("Invalid --prefix")
    if args.name is not None and (not args.name or not args.name[0].isalnum() or not all(
        c.isalnum() or c in "_-" for c in args.name
    )):
        parser.error("Invalid --name; use letters, digits, underscores or hyphens")
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
        if part["id"] not in ("body", "head") and part.get("status") in (
            None, "unfitted", "staged_unfitted",
        ):
            part["status"] = "provisional_visible_unfitted"
    manifest["preview_layout"] = "overlay"
    manifest["workable_version"] = WORKABLE_VERSION
    manifest["workable_warnings"] = [
        "All configured independent painted meshes are included, even if they overlap.",
        "Generated gloves and clothing may include unwanted mannequin geometry.",
        "Landmark-box alignment remains approximate; edit transforms in assembly.json.",
        "Gloves are split into left/right working copies with wrist anchors; inspect orientation.",
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


def write_assembly_gallery(folder: Path, card: dict, source_paths: dict) -> Path:
    """Static local gallery for a complete, non-destructive character preview."""
    directions = ("front", "side", "back", "threequarter")
    for direction in directions:
        picture = folder / f"preview_{direction}.png"
        if not picture.is_file() or picture.stat().st_size == 0:
            raise RuntimeError(f"Missing assembled render: {picture}")
    for filename in ("preview.blend", "preview.glb", "assembly.json", "measurements.json"):
        source = folder / filename
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"Missing assembled output: {source}")
    tiles = "".join(
        f'<figure><a href="preview_{direction}.png"><img loading="lazy" '
        f'src="preview_{direction}.png" alt="Assembled {escape(card["name"])} '
        f'{direction} view"></a><figcaption>{direction}</figcaption></figure>'
        for direction in directions
    )
    links = " | ".join(
        f'<a href="{filename}">{label}</a>'
        for filename, label in (
            ("preview.blend", "Open in Blender"),
            ("preview.glb", "Combined GLB"),
            ("assembly.json", "Editable transforms"),
            ("measurements.json", "Measurements"),
        )
    )
    # Only the active card's parts are linked. Historical separate hair assets
    # are left on disk, but never appear in the assembled character.
    components = "".join(
        '<li>' + escape(part["label"]) + ' — <a href="../'
        + escape(source.parent.name, quote=True) + '/05_painted.glb">'
        + escape(part_id) + ' source GLB</a></li>'
        for part_id, source in source_paths.items()
        for part in card["parts"] if part["id"] == part_id
    )
    metrics = json.loads((folder / "measurements.json").read_text(encoding="utf-8"))
    coverage = metrics.get("clothing_replacement", {})
    coverage_note = (
        f'<p>Upper garment coverage: {escape(str(coverage.get("status", "off")))}; '
        f'underlying body faces removed on assembly copies: '
        f'{int(coverage.get("removed_faces", 0))}. '
        'The original body remains available in the hidden backup collection '
        'when a mask is applied.</p>'
    )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(card["name"])} — assembled prototype</title>'
        '<style>body{font:16px/1.5 system-ui,sans-serif;margin:0 auto;'
        'padding:24px;max-width:1400px;background:#111821;color:#e8eff6}'
        'a{color:#8acfff}.views{display:grid;grid-template-columns:'
        'repeat(auto-fit,minmax(220px,1fr));gap:14px}'
        'figure{margin:0}img{width:100%;border-radius:8px;background:#263343}'
        'figcaption{text-align:center}p{max-width:820px}li{padding:3px}</style>'
        '</head><body>'
        f'<h1>{escape(card["name"])} — assembled prototype</h1>'
        '<p>All configured components are imported from independently generated '
        'painted GLBs. Placement and neck cuts are approximate and editable. '
        'Overlapping fabric, mannequin remnants and unsealed seams are expected; '
        'this is not a rigged or production-ready game character.</p>'
        f'<p>{links}</p>{coverage_note}<div class="views">{tiles}</div>'
        f'<h2>Source components ({len(source_paths)})</h2><ul>{components}</ul>'
        '</body></html>'
    )
    index = folder / "index.html"
    if index.is_symlink():
        raise RuntimeError(f"Refusing symlink assembly gallery: {index}")
    index.write_text(page, encoding="utf-8")
    return index


def assemble(args):
    card_path = args.card.expanduser().resolve()
    card = load_card(card_path)
    ids = [p["id"] for p in card["parts"]]
    if "body" not in ids or "head" not in ids:
        raise RuntimeError("Workable assembly requires body and head")
    output_root = args.output_dir.expanduser().resolve()
    source_paths = sources(card, args.prefix, output_root)
    target_name = args.name or args.prefix + "_workable_character"
    # Never overwrite an approved body/head assembly, a painted part folder,
    # or the separate prototype gallery.
    protected_names = {
        args.prefix + "_assembly", args.prefix + "_prototypes",
        *[source.parent.name for source in source_paths.values()],
    }
    if target_name in protected_names:
        raise RuntimeError(
            f"Assembly output name {target_name!r} is reserved for existing assets; "
            "choose a distinct --assembly NAME"
        )
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
    print("Upper garment body replacement:",
          "ENABLED (working copies only)" if args.replace_upper_body else "off")
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

    fresh_assembly = not manifest_file.exists()
    if fresh_assembly:
        # Initial geometry measurement includes every unmodified part, staged
        # separately. This is a NEW folder, not the approved head/body preview.
        print("[WORKABLE] Import and measure all standalone meshes", flush=True)
        assemble_preview(card_path, name=target_name, run_prefix=args.prefix,
                         output_root=output_root, blender=args.blender,
                         layout="overlay", include_all_parts=True,
                         source_stage="painted")
    if not manifest_file.is_file():
        raise RuntimeError("Missing assembly manifest after Blender import")

    # Validate any existing manifest BEFORE rebuilding it. In particular,
    # an old seven-part scene containing the removed hair component must never
    # be overwritten by a six-part run, even if its measurements are missing.
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (manifest.get("character_id") != card["id"] or
            manifest.get("run_prefix") != args.prefix):
        raise RuntimeError("Existing workable folder belongs to another run")
    previous_ids = [part["id"] for part in manifest.get("parts", [])]
    if previous_ids != ids:
        raise RuntimeError(
            "Part inventory changed (for example, an older seven-part assembly "
            "may still include the removed hair component). Keep it intact and "
            "choose a fresh --assembly NAME with the same --prefix."
        )
    actual_sources = {part["id"]: Path(part["source"]).resolve() for part in manifest["parts"]}
    expected_sources = {ident: source.resolve() for ident, source in source_paths.items()}
    if actual_sources != expected_sources:
        raise RuntimeError(
            "Existing assembly uses different component source files; "
            "choose a fresh --assembly NAME instead of overwriting manual work."
        )

    requested_mode = (UPPER_REPLACEMENT_MODE if args.replace_upper_body else "off")
    existing_mode = manifest.get("clothing_replacement", {}).get("mode", "off")
    if not fresh_assembly and requested_mode != existing_mode:
        raise RuntimeError(
            "The requested upper-body replacement differs from the existing "
            "assembly. Choose a fresh --assembly NAME to protect manual work."
        )

    if not measures.is_file():
        assemble_preview(card_path, name=target_name, run_prefix=args.prefix,
                         output_root=output_root, blender=args.blender, rebuild=True)

    initial = manifest.get("workable_version") != WORKABLE_VERSION
    if initial or args.refit:
        fit_manifest(manifest_file, measures, refit=args.refit)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if use_prior_approved_head(manifest, prior):
            print("[WORKABLE] Preserved prior body/head alignment and cuts")
        else:
            print("[WORKABLE] No matching prior body/head fit; using bounds estimate")
        enable_workable_parts(manifest)
        if args.replace_upper_body:
            manifest["clothing_replacement"] = upper_replacement_plan()
        save_manifest(manifest_file, manifest)
    else:
        print("[WORKABLE] Preserving previously edited transforms and visibility")

    print("[WORKABLE] Exporting editable scene with configured parts", flush=True)
    assemble_preview(card_path, name=target_name, run_prefix=args.prefix,
                     output_root=output_root, blender=args.blender, rebuild=True)
    render_scene(args.blender, folder)
    index = write_assembly_gallery(folder, card, source_paths)
    print("\n[WORKABLE] Complete:", folder)
    print("Blender:", folder / "preview.blend")
    print("GLB:", folder / "preview.glb")
    print("Transforms:", manifest_file)
    print("Renders:", folder / "preview_front.png", "(+ side/back/threequarter)")
    if args.replace_upper_body:
        report = json.loads(measures.read_text(encoding="utf-8")).get(
            "clothing_replacement", {}
        )
        print("Upper-garment body masking:", report.get("status"),
              "covered faces:", report.get("removed_faces"))
    print("Gallery:", index)
    print("Open locally: firefox", index)
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
