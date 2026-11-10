"""Optional real-Blender round-trip validation for already-textured static GLBs.

No GPU inference is launched. This command never modifies its source asset,
writes all artifacts to outputs/<name>/ by default, and refuses to reuse
nonempty validation folders to avoid accidental overwrite.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from ai3d.export.validation import readable_glb
from ai3d.optimization.blender import build_finalize_command
from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory
from ai3d.pipeline_runner import Runner


FINALIZER = Path(__file__).resolve().parent / "optimization/blender_finalize.py"


def sha256_file(path: Path) -> str:
    """Hash a file without reading the entire mesh into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_blender(
    source: Path,
    *,
    name: str,
    target_faces: int = 15000,
    blender: str = "blender",
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Round-trip a textured static GLB through Blender and inspect the result.

    On real runs, preserve the original input and save:
      <output_dir>/<name>/blender_validated.glb
      <output_dir>/<name>/blender_validation.json
      <output_dir>/<name>/logs/blender_validation.log

    A structural pass is not a guarantee of visual/texture fidelity.
    """
    if target_faces < 100:
        raise ValueError("--target-faces must be >= 100")

    source = Path(source).expanduser().resolve()
    original = readable_glb(source, need_texture=True)
    original_hash = sha256_file(source)

    run_dir = run_directory(name, output_dir or DEFAULT_OUTPUT_ROOT)
    destination = run_dir / "blender_validated.glb"
    report_path = run_dir / "blender_validation.json"

    if source == destination.resolve():
        raise RuntimeError("Refusing to overwrite the source GLB")
    if run_dir.is_symlink():
        raise RuntimeError(f"Refusing symlink output directory: {run_dir}")
    if run_dir.is_dir() and any(run_dir.iterdir()):
        raise RuntimeError(f"Validation output directory is not empty: {run_dir}. Choose a fresh --name.")
    if run_dir.exists() and not run_dir.is_dir():
        raise RuntimeError(f"Validation destination is not a directory: {run_dir}")

    resolved_blender = shutil.which(str(blender))
    if not resolved_blender and not dry_run:
        raise RuntimeError(f"Blender executable not found: {blender}")
    executable = resolved_blender or str(blender)
    command = build_finalize_command(
        executable, FINALIZER, source, destination, target_faces,
    )
    if dry_run:
        print("DRY RUN: Blender will not be launched; no directories created.")
        print("Source:", source)
        print("Destination:", destination)
        print("Report:", report_path)
        print("Command:", subprocess.list2cmdline(command))
        return {"status": "dry_run", "source": str(source), "output": str(destination)}

    # All source checks and no-overwrite checks happen before creating files.
    runner = Runner(run_dir, resume=False, force=False, dry=False)
    runner.command("blender_validation", command)

    processed = readable_glb(destination, need_texture=True)
    if sha256_file(source) != original_hash:
        raise RuntimeError("Input mesh changed during validation; investigate immediately")

    checks = {
        "source_unchanged": True,
        "has_uv0": bool(processed["uv0"]),
        "has_base_color_texture": processed["base_color_primitives"] > 0,
        "has_images": processed["images"] > 0,
        "has_materials": processed["materials"] > 0,
        "triangle_count_not_increased": processed["triangles"] <= original["triangles"],
    }
    warnings = []
    if original["triangles"] > target_faces and processed["triangles"] > target_faces * 1.05:
        warnings.append(
            "Final triangle count remains more than 5% above target; "
            "Blender decimation uses an approximate ratio."
        )
    if processed["images"] < original["images"]:
        warnings.append("Output has fewer image entries than input; inspect materials manually")
    if processed["materials"] < original["materials"]:
        warnings.append("Output has fewer materials than input; inspect materials manually")

    passed = all(checks.values())
    report = {
        "status": "structural_pass" if passed else "structural_fail",
        "source": original,
        "source_sha256": original_hash,
        "output": processed,
        "target_triangles": target_faces,
        "checks": checks,
        "warnings": warnings,
        "manual_visual_review_required": True,
        "notes": [
            "Inspect the GLB in Blender Material Preview from all sides.",
            "Check UV seams, skin/face colors, normals, and material appearance.",
            "This is not a complete glTF conformance or texture fidelity check.",
            "Static-mesh finalization does not retain rigs or animations.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "input_triangles": original["triangles"],
        "output_triangles": processed["triangles"],
        "textures": processed["textures"],
        "images": processed["images"],
        "materials": processed["materials"],
        "warnings": warnings,
        "output": str(destination),
        "report": str(report_path),
        "visual_review": "required",
    }, indent=2))
    if not passed:
        raise RuntimeError(f"Blender round-trip structural validation failed: {report_path}")
    return report


def parse_and_validate(argv: list[str] | None = None) -> dict:
    """CLI parser for optional local Blender validation."""
    parser = argparse.ArgumentParser(
        prog="ai3d validate-blender",
        description="Optimize and structurally validate an existing textured static GLB",
    )
    parser.add_argument("source", type=Path, help="Existing textured GLB (never modified)")
    parser.add_argument("--name", required=True, help="New output run name")
    parser.add_argument("--target-faces", type=int, default=15000,
                        help="Approximate triangle target (default: 15000)")
    parser.add_argument("--blender", default="blender", help="Blender executable")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT,
                        help="Generated output root (default: <repository>/outputs)")
    parser.add_argument("--dry-run", action="store_true", help="Print command; write nothing")
    options = parser.parse_args(argv)
    return validate_blender(
        options.source, name=options.name, target_faces=options.target_faces,
        blender=options.blender, output_dir=options.output_dir,
        dry_run=options.dry_run,
    )
