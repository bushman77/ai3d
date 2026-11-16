#!/usr/bin/env python3
"""Prepare tighter anatomical reference crops and anchor metadata for Mara.

Read-only with respect to source assets: verifies the approved master image,
creates a new output directory with tighter crops, a JSON manifest, and a
simple HTML review page.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

try:
    from PIL import Image, ImageDraw
except Exception as exc:  # pragma: no cover
    raise SystemExit("ERROR: Pillow is required (python3-pil).") from exc

EXPECTED_SHA256 = "144d06916502ecb524e4113f8bc11b9ab80bfa6714290773a7046d23bd4e2791"
DEFAULT_INPUT = Path("approved_references/mara_body_front_approved.png")
DEFAULT_OUTPUT = Path("outputs/mara_reference_prepare_v1")


@dataclass(frozen=True)
class PartSpec:
    id: str
    label: str
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2 in master image coordinates
    anchors: Dict[str, Tuple[int, int]]
    suitability: str
    notes: str
    side: str | None = None


# Anatomical left/right are from Mara's perspective.
# Because the original is 512x512 and hands/feet are tiny, these are still
# approximate planning references rather than final reconstruction inputs.
PARTS: tuple[PartSpec, ...] = (
    PartSpec(
        id="torso_pelvis",
        label="Torso + pelvis",
        bbox=(176, 44, 337, 424),
        anchors={
            "neck": (256, 67),
            "left_shoulder": (323, 96),
            "right_shoulder": (189, 96),
            "waist_center": (256, 195),
            "left_hip": (292, 263),
            "right_hip": (220, 263),
            "pelvis_center": (256, 283),
        },
        suitability="provisional",
        notes="Good enough for silhouette planning and later fitting anchors. Not sufficient alone for final high-detail reconstruction.",
    ),
    PartSpec(
        id="head",
        label="Head + neck",
        bbox=(193, 4, 319, 138),
        anchors={
            "crown": (256, 9),
            "chin": (256, 106),
            "left_ear_region": (285, 60),
            "right_ear_region": (227, 60),
            "neck_base": (256, 127),
        },
        suitability="strong",
        notes="Most usable crop from the master image. Still front-view only.",
    ),
    PartSpec(
        id="left_arm",
        label="Left arm (Mara left / viewer right)",
        bbox=(278, 77, 501, 143),
        anchors={
            "shoulder": (324, 96),
            "elbow": (405, 98),
            "wrist": (474, 99),
        },
        suitability="provisional",
        notes="Usable for approximate arm span and contour. Limited thickness/depth information from frontal view.",
        side="left",
    ),
    PartSpec(
        id="right_arm",
        label="Right arm (Mara right / viewer left)",
        bbox=(11, 77, 234, 143),
        anchors={
            "shoulder": (188, 96),
            "elbow": (107, 98),
            "wrist": (38, 99),
        },
        suitability="provisional",
        notes="Usable for approximate arm span and contour. Limited thickness/depth information from frontal view.",
        side="right",
    ),
    PartSpec(
        id="left_hand",
        label="Left hand (Mara left / viewer right)",
        bbox=(424, 80, 510, 137),
        anchors={
            "wrist": (474, 99),
            "palm_center": (457, 101),
            "fingertips_center": (499, 100),
            "thumb_tip_region": (472, 85),
        },
        suitability="weak",
        notes="Too small and soft for reliable independent mesh generation from this image alone.",
        side="left",
    ),
    PartSpec(
        id="right_hand",
        label="Right hand (Mara right / viewer left)",
        bbox=(2, 80, 88, 137),
        anchors={
            "wrist": (38, 99),
            "palm_center": (55, 101),
            "fingertips_center": (13, 100),
            "thumb_tip_region": (40, 85),
        },
        suitability="weak",
        notes="Too small and soft for reliable independent mesh generation from this image alone.",
        side="right",
    ),
    PartSpec(
        id="left_leg",
        label="Left leg (Mara left / viewer right)",
        bbox=(243, 249, 311, 500),
        anchors={
            "hip": (292, 263),
            "knee": (285, 382),
            "ankle": (280, 462),
        },
        suitability="provisional",
        notes="Useful for coarse silhouette and anchor planning. No side/depth info.",
        side="left",
    ),
    PartSpec(
        id="right_leg",
        label="Right leg (Mara right / viewer left)",
        bbox=(201, 249, 269, 500),
        anchors={
            "hip": (220, 263),
            "knee": (227, 382),
            "ankle": (232, 462),
        },
        suitability="provisional",
        notes="Useful for coarse silhouette and anchor planning. No side/depth info.",
        side="right",
    ),
    PartSpec(
        id="left_foot",
        label="Left foot (Mara left / viewer right)",
        bbox=(252, 450, 310, 511),
        anchors={
            "ankle": (280, 462),
            "toe_center": (281, 502),
            "heel_region": (264, 474),
        },
        suitability="weak",
        notes="Foot is too small in the master image for high-quality stand-alone reconstruction.",
        side="left",
    ),
    PartSpec(
        id="right_foot",
        label="Right foot (Mara right / viewer left)",
        bbox=(201, 450, 259, 511),
        anchors={
            "ankle": (232, 462),
            "toe_center": (229, 502),
            "heel_region": (246, 474),
        },
        suitability="weak",
        notes="Foot is too small in the master image for high-quality stand-alone reconstruction.",
        side="right",
    ),
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clamp_bbox(box: Tuple[int, int, int, int], width: int, height: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def localize_anchors(anchors: Dict[str, Tuple[int, int]], x1: int, y1: int) -> Dict[str, list[int]]:
    return {name: [x - x1, y - y1] for name, (x, y) in anchors.items()}


def render_crop(master: Image.Image, spec: PartSpec, out_path: Path) -> dict:
    width, height = master.size
    x1, y1, x2, y2 = clamp_bbox(spec.bbox, width, height)
    crop = master.crop((x1, y1, x2, y2))
    crop.save(out_path)
    return {
        "id": spec.id,
        "label": spec.label,
        "bbox_master": [x1, y1, x2, y2],
        "crop_size": [x2 - x1, y2 - y1],
        "anchors_master": {k: list(v) for k, v in spec.anchors.items()},
        "anchors_local": localize_anchors(spec.anchors, x1, y1),
        "suitability": spec.suitability,
        "side": spec.side,
        "notes": spec.notes,
        "file": out_path.name,
    }


def draw_overlay(master: Image.Image, out_path: Path) -> None:
    img = master.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = {
        "strong": (80, 200, 120, 88),
        "provisional": (240, 180, 60, 88),
        "weak": (220, 70, 70, 88),
    }
    outline = {
        "strong": (80, 200, 120, 220),
        "provisional": (240, 180, 60, 220),
        "weak": (220, 70, 70, 220),
    }
    for spec in PARTS:
        x1, y1, x2, y2 = spec.bbox
        draw.rectangle((x1, y1, x2, y2), fill=colors[spec.suitability], outline=outline[spec.suitability], width=2)
        tx, ty = x1 + 4, max(0, y1 - 14)
        draw.text((tx, ty), spec.id, fill=(255, 255, 255, 255))
        for ax, ay in spec.anchors.values():
            r = 3
            draw.ellipse((ax - r, ay - r, ax + r, ay + r), fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
    out = Image.alpha_composite(img, overlay).convert("RGB")
    out.save(out_path)


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_html(out_dir: Path, manifest: dict) -> None:
    cards = []
    for part in manifest["parts"]:
        anchors = "<br>".join(
            f"<code>{html_escape(name)}</code>: {coords[0]}, {coords[1]}"
            for name, coords in part["anchors_master"].items()
        )
        cards.append(
            f"""
            <div class='card'>
              <h3>{html_escape(part['id'])}</h3>
              <img src='{html_escape(part['file'])}' alt='{html_escape(part['id'])}'>
              <p><strong>{html_escape(part['label'])}</strong></p>
              <p>Suitability: <span class='badge {html_escape(part['suitability'])}'>{html_escape(part['suitability'])}</span></p>
              <p>Master bbox: <code>{part['bbox_master']}</code></p>
              <p>Crop size: <code>{part['crop_size']}</code></p>
              <p>Anchors:<br>{anchors}</p>
              <p>{html_escape(part['notes'])}</p>
            </div>
            """.strip()
        )
    html = f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<title>Mara anatomical reference preparation</title>
<style>
body {{ font-family: sans-serif; background: #0f1720; color: #e5edf5; margin: 24px; }}
h1, h2 {{ margin-bottom: 8px; }}
p, li {{ line-height: 1.4; }}
.section {{ margin-bottom: 28px; }}
img.master {{ max-width: 420px; border: 1px solid #445; background: #fff; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
.card {{ background: #1a2431; border: 1px solid #2d3d50; border-radius: 10px; padding: 12px; }}
.card img {{ width: 100%; height: auto; background: #c9c9c9; display: block; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.9em; }}
.badge.strong {{ background: #215f38; }}
.badge.provisional {{ background: #7a5612; }}
.badge.weak {{ background: #7a1f1f; }}
code {{ color: #f7d58d; }}
.small {{ color: #b7c6d3; font-size: 0.95em; }}
</style>
</head>
<body>
  <h1>Mara Venn — anatomical reference preparation</h1>
  <div class='section'>
    <p><strong>Source master:</strong> {html_escape(manifest['source_master'])}</p>
    <p><strong>Master SHA-256:</strong> <code>{html_escape(manifest['source_sha256'])}</code></p>
    <p class='small'>These outputs are planning assets only. They preserve the approved Mara image while introducing tighter crops, anchor metadata, and readiness labels for later image-conditioned fitting work.</p>
    <img class='master' src='master_overlay.png' alt='Master overlay'>
  </div>
  <div class='section'>
    <h2>Prepared part crops</h2>
    <div class='grid'>
      {' '.join(cards)}
    </div>
  </div>
</body>
</html>
"""
    (out_dir / "review.html").write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Mara anatomical crops and anchors")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Approved Mara master PNG")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate and describe outputs only")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output directory")
    args = parser.parse_args()

    src = args.input.expanduser()
    out_dir = args.output.expanduser()

    if not src.is_file():
        raise SystemExit(f"ERROR: Missing approved master image: {src}")
    digest = sha256_file(src)
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            "ERROR: Approved master image checksum mismatch. "
            f"Expected {EXPECTED_SHA256}, got {digest}"
        )

    if out_dir.exists() and not args.overwrite and not args.dry_run:
        raise SystemExit(f"ERROR: Output directory already exists: {out_dir} (use --overwrite)")

    print(f"Verified master image: {src} ({digest[:12]}…)")
    print(f"Prepared parts: {', '.join(spec.id for spec in PARTS)}")
    print("Readiness summary: head=strong; torso/arms/legs=provisional; hands/feet=weak")
    if args.dry_run:
        print(f"Would create: {out_dir}/master.png, master_overlay.png, part PNGs, reference_parts.json, review.html")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    master = Image.open(src).convert("RGB")
    master.save(out_dir / "master.png")
    draw_overlay(master, out_dir / "master_overlay.png")

    parts_manifest = []
    for spec in PARTS:
        part_path = out_dir / f"{spec.id}.png"
        parts_manifest.append(render_crop(master, spec, part_path))

    manifest = {
        "version": 1,
        "character_id": "mara_venn",
        "character_name": "Mara Venn",
        "source_master": str(src),
        "source_sha256": digest,
        "image_size": list(master.size),
        "notes": [
            "Outputs are planning references only, not direct reconstruction inputs.",
            "Anatomical left/right are from Mara's perspective.",
            "Hands and feet are flagged weak because the approved full-body master image lacks enough pixel detail.",
            "Use anchors as initial fitting targets for later image-conditioned stages.",
        ],
        "parts": parts_manifest,
    }
    (out_dir / "reference_parts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_html(out_dir, manifest)

    print(f"Created: {out_dir / 'reference_parts.json'}")
    print(f"Created: {out_dir / 'review.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
