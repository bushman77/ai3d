"""Conservative, non-destructive landmark-box fitting for humanoid parts.

This uses estimated body fractions and measured mesh extents, not detected
joints, clothing projection, or anatomical registration.
retopology, seam welding, skinning, or an artistic quality guarantee.
The assembly GLB is exported separately from the source GLBs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import tempfile

FIT_VERSION = 3


def _bounds(report: dict, part_id: str) -> dict:
    matches = [item for item in report.get("components", []) if item.get("id") == part_id]
    if len(matches) != 1:
        raise RuntimeError(f"Missing or ambiguous measured component: {part_id}")
    bounds = matches[0]["bounds_with_user_transform"]
    if any(len(bounds[k]) != 3 or not all(math.isfinite(v) for v in bounds[k])
           for k in ("min", "max")):
        raise RuntimeError(f"Invalid measured bounds for {part_id}")
    return bounds


def _raw_bounds(measured: dict, transform: dict) -> dict:
    """Invert AI3D's zero-rotation controller to recover imported bounds."""
    scale = transform["scale"]
    location = transform["position"]
    rotation = transform["rotation_deg"]
    if any(abs(v) > 0.001 for v in rotation):
        raise RuntimeError("Auto-refit requires zero controller rotation; preserve manual fitting or reset rotation")
    if any(v <= 0 for v in scale):
        raise RuntimeError("Auto-fit requires positive part scale")
    lo = [(measured["min"][i] - location[i]) / scale[i] for i in range(3)]
    hi = [(measured["max"][i] - location[i]) / scale[i] for i in range(3)]
    return {"min": lo, "max": hi,
            "size": [hi[i] - lo[i] for i in range(3)],
            "center": [(lo[i] + hi[i]) / 2 for i in range(3)]}


def _place(part: dict, source: dict, *, size_by_axis: tuple[int, float],
           target_center: list[float] | None = None,
           target_top: float | None = None) -> None:
    axis, desired = size_by_axis
    current = source["size"][axis]
    if not math.isfinite(current) or current <= 1e-6:
        raise RuntimeError(f"Degenerate {part['id']} mesh bounds")
    scale = desired / current
    if not 0.001 < scale < 1000:
        raise RuntimeError(f"Implausible auto-fit scale for {part['id']}: {scale}")
    offset = [0.0, 0.0, 0.0]
    if target_center is not None:
        offset = [target_center[i] - source["center"][i] * scale for i in range(3)]
    if target_top is not None:
        offset[2] = target_top - source["max"][2] * scale
    part["transform"] = {
        "position": [round(v, 7) for v in offset],
        "rotation_deg": [0.0, 0.0, 0.0],
        "scale": [round(scale, 7)] * 3,
    }
    part["status"] = "heuristic_fit_unverified"


def _fit_to_landmark_box(part: dict, source: dict, *,
                         center: tuple[float, float, float],
                         width: float, depth: float, height: float) -> None:
    """Fit a *copy* to an approximate anatomical box using separate XYZ scales.

    The older code scaled outfits from X-width alone. A narrow pair of pants
    could then extend above the head. Here both the target vertical extent
    and the maximum lateral extent are explicit, and each axis is measured.
    This is a visual fitting heuristic, not garment registration.
    """
    desired = (width, depth, height)
    dimensions = source["size"]
    if any(not math.isfinite(value) or value <= 1e-6 for value in dimensions):
        raise RuntimeError(f"Degenerate {part['id']} mesh bounds")
    scales = [desired[i] / dimensions[i] for i in range(3)]
    if any(not math.isfinite(value) or not 0.001 < value < 1000
           for value in scales):
        raise RuntimeError(f"Implausible landmark fit scale for {part['id']}")
    part["transform"] = {
        "position": [round(center[i] - scales[i] * source["center"][i], 7)
                     for i in range(3)],
        "rotation_deg": [0.0, 0.0, 0.0],
        "scale": [round(value, 7) for value in scales],
    }
    part["status"] = "landmark_box_fit_unverified"


def _stamp(manifest: dict) -> dict:
    return {
        part["id"]: [Path(part["source"]).stat().st_size,
                     Path(part["source"]).stat().st_mtime_ns]
        for part in manifest["parts"]
    }


def fit_manifest(manifest_path: Path, measurements_path: Path, *, refit: bool = False) -> bool:
    """Return True if a new manifest was written; preserve existing work by default."""
    manifest_path = Path(manifest_path).expanduser().resolve(strict=True)
    measurements_path = Path(measurements_path).expanduser().resolve(strict=True)
    if manifest_path.name != "assembly.json" or not manifest_path.is_file():
        raise RuntimeError("Expected an existing assembly.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(measurements_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 1 or report.get("character_id") != manifest.get("character_id"):
        raise RuntimeError("Assembly and measurements do not match")
    parts = {part["id"]: part for part in manifest["parts"]}
    if "body" not in parts or "head" not in parts:
        raise RuntimeError("Automatic fit requires body and head component IDs")
    signatures = _stamp(manifest)
    previous = manifest.get("auto_fit", {})
    if (not refit and previous.get("version") == FIT_VERSION
            and previous.get("source_signatures") == signatures):
        print("[FIT] Existing fit preserved; use --refit to replace manual adjustments")
        return False

    raw = {}
    for part_id, part in parts.items():
        raw[part_id] = _raw_bounds(_bounds(report, part_id), part["transform"])
    body = raw["body"]
    h = body["size"][2]
    if not math.isfinite(h) or h < 0.2:
        raise RuntimeError(f"Unrealistic body height: {h}")
    cx, cy = body["center"][:2]
    crown = body["max"][2]
    base = body["min"][2]
    # Human-scale estimates; inspect the output before shipping any game asset.
    _place(parts["head"], raw["head"], size_by_axis=(2, 0.20 * h),
           target_center=[cx, cy, 0.0], target_top=crown)
    cut_z = crown - 0.17 * h
    # Both cuts use the same world-Z plane. They intentionally leave open
    # boundaries; neither automatic welding nor neck anatomy is inferred.
    for part_id, side in (("body", "below"), ("head", "above")):
        part = parts[part_id]
        part["visible"] = True
        part["include_in_preview"] = True
        part["cut"] = {"mode": "apply", "plane_z": round(cut_z, 7),
                       "keep": side, "show_guide": False}

    # Anatomical target regions are expressed as fractions of the existing
    # full-body height. These are not recovered joints or segmentation masks.
    # They intentionally prevent the lower outfit from covering the face.
    body_width = body["size"][0]
    body_depth = body["size"][1]
    if body_width <= 1e-6 or body_depth <= 1e-6:
        raise RuntimeError("Degenerate body width/depth")
    if "upper_outfit" in parts:
        _fit_to_landmark_box(
            parts["upper_outfit"], raw["upper_outfit"],
            center=(cx, cy, base + 0.72 * h),
            width=0.96 * body_width,
            depth=1.04 * body_depth,
            height=0.36 * h,
        )
    if "lower_outfit" in parts:
        _fit_to_landmark_box(
            parts["lower_outfit"], raw["lower_outfit"],
            center=(cx, cy, base + 0.29 * h),
            width=min(0.50 * body_width, 0.34 * h),
            depth=0.88 * body_depth,
            height=0.54 * h,
        )

    if "hands" in parts:
        # A pair of Hunyuan gloves is often one side-by-side mesh. Do not
        # stretch the entire pair across the abdomen: it must be split into
        # two spatial halves and positioned independently by Blender.
        #
        # The imported pair remains at its original measured transform;
        # Blender applies this separate plan to WORKING copies only.
        parts["hands"]["transform"] = {
            "position": [0.0, 0.0, 0.0],
            "rotation_deg": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        }
        wrist_x = 0.45 * body_width
        parts["hands"]["pair_layout"] = {
            "mode": "split_x_to_wrists_v1",
            "left_wrist": [round(cx - wrist_x, 7), round(cy, 7),
                           round(base + 0.55 * h, 7)],
            "right_wrist": [round(cx + wrist_x, 7), round(cy, 7),
                            round(base + 0.55 * h, 7)],
            "hand_length": round(0.12 * h, 7),
            "hand_width": round(0.09 * h, 7),
        }
        parts["hands"]["status"] = "glove_pair_split_planned"

    # The existing full-body mesh may still include some suit/glove geometry.
    # These placements overlay it until a body-surface replacement pass exists.
    if "equipment" in parts:
        _place(parts["equipment"], raw["equipment"], size_by_axis=(0, 0.27 * h),
               target_center=[cx, cy - 0.05 * h, base + 0.55 * h])
        parts["equipment"]["status"] = "belt_and_pouches_fit_unverified"

    # Preserve legacy part compatibility when explicitly present in old cards.
    if "outfit" in parts:
        _place(parts["outfit"], raw["outfit"], size_by_axis=(2, 0.37 * h),
               target_center=[cx, cy, base + 0.71 * h])
    if "hair" in parts:
        _place(parts["hair"], raw["hair"], size_by_axis=(2, 0.18 * h),
               target_center=[cx, cy, 0.0], target_top=crown)

    manifest["preview_layout"] = "overlay"
    manifest["auto_fit"] = {
        "version": FIT_VERSION,
        "source_signatures": signatures,
        "neck_cut_z": round(cut_z, 7),
        "warnings": [
            "Bounds-derived positions are approximate and not anatomical landmarks.",
            "Neck cuts create unsealed boundaries; inspect contours and materials.",
            "Upper/lower clothing uses approximate height, width and depth target boxes.",
            "Glove halves are split and placed by Blender; review finger orientations.",
            "No automatic removal of underlying suit geometry or mannequin remnants.",
            "No rig, skinning, animation, retopology, or seam welding is performed.",
        ],
    }
    # Atomic update: never touch the generated mesh files or the source card.
    fd, temporary = tempfile.mkstemp(prefix=".auto-fit-", dir=manifest_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(manifest, out, indent=2, allow_nan=False)
            out.write("\n")
        os.replace(temporary, manifest_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"[FIT] Updated {manifest_path} (approximate fit; source models unchanged)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--refit", action="store_true")
    args = parser.parse_args()
    fit_manifest(args.manifest, args.measurements, refit=args.refit)


if __name__ == "__main__":
    main()
