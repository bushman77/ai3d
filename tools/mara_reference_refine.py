#!/usr/bin/env python3
"""Non-destructive, seam-aware *review* of Mara's approved 512px master.

Makes tighter crops, editable coarse polygon mattes, and 2-D joint guides.
These are NOT automatically verified segmentation masks, 3-D measurements,
or inference-ready Hunyuan inputs. This script never unlocks generation.

Requires Python 3.10+ and Pillow. Run from the ai3d repository root.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

MASTER = Path("approved_references/mara_body_front_approved.png")
OUT = Path("outputs/mara_reference_refine_v1")
SHA256 = "144d06916502ecb524e4113f8bc11b9ab80bfa6714290773a7046d23bd4e2791"


@dataclass(frozen=True)
class Part:
    name: str
    box: tuple[int, int, int, int]
    polygon: tuple[tuple[int, int], ...]
    anchors: dict[str, tuple[int, int]]
    readiness: str
    parent: Optional[str] = None
    side: Optional[str] = None
    detail: str = ""


# Approximate image-coordinate polygons, NOT measured anatomical outlines.
# T-pose, x grows toward image right, y grows down. Mara's anatomical LEFT
# appears on image RIGHT. Data is deliberately editable in one place.
PARTS = (
    Part("torso_pelvis", (188, 102, 324, 294), (
        (242, 105), (268, 105), (303, 112), (313, 124),
        (309, 141), (299, 155), (299, 174), (291, 190),
        (297, 217), (303, 255), (298, 282), (288, 291),
        (224, 291), (214, 282), (209, 255), (215, 217),
        (221, 190), (213, 174), (213, 155), (203, 141),
        (199, 124), (209, 112)), {
        "neck": (256, 108),
        "left_shoulder": (309, 123), "right_shoulder": (203, 123),
        "left_hip": (280, 283), "right_hip": (232, 283),
        "pelvis_center": (256, 278),
    }, "review_only", detail="Upper torso and pelvis only. Shoulder/hip cross-sections are estimates."),
    Part("head", (219, 14, 295, 119), (
        (249, 18), (264, 18), (281, 24), (286, 37),
        (286, 65), (279, 88), (270, 100), (267, 110),
        (273, 116), (239, 116), (245, 110), (242, 100),
        (233, 88), (226, 65), (226, 37), (231, 24)), {
        "crown": (256, 20), "chin": (256, 99), "neck_joint": (256, 108),
    }, "review_only", "torso_pelvis", detail="Contains face and neck; additional view needed for back-of-head depth."),
    Part("left_arm", (301, 105, 456, 147), (
        (303, 113), (328, 116), (363, 117), (401, 116),
        (446, 115), (452, 119), (452, 132), (445, 132),
        (401, 131), (364, 134), (331, 136), (307, 141)), {
        "shoulder": (309, 123), "elbow": (385, 124), "wrist": (449, 122),
    }, "review_only", "torso_pelvis", "left", "Viewer-right arm. Shoulder and wrist seam bands intentionally overlap adjacent pieces."),
    Part("right_arm", (56, 105, 211, 147), (
        (209, 113), (184, 116), (149, 117), (111, 116),
        (66, 115), (60, 119), (60, 132), (67, 132),
        (111, 131), (148, 134), (181, 136), (205, 141)), {
        "shoulder": (203, 123), "elbow": (127, 124), "wrist": (63, 122),
    }, "review_only", "torso_pelvis", "right", "Viewer-left arm. Shoulder and wrist seam bands intentionally overlap adjacent pieces."),
    Part("left_hand", (443, 105, 506, 143), (
        (448, 114), (456, 113), (465, 110), (476, 107),
        (484, 110), (495, 112), (503, 117), (502, 127),
        (492, 131), (482, 135), (467, 136), (454, 131), (447, 129)), {
        "wrist": (449, 122), "palm": (466, 122), "fingertip_region": (496, 121),
    }, "weak", "left_arm", "left", "Small master-image hands. Mask is only a placement guide; fingers need a separate high-detail source."),
    Part("right_hand", (6, 105, 69, 143), (
        (64, 114), (56, 113), (47, 110), (36, 107),
        (28, 110), (17, 112), (9, 117), (10, 127),
        (20, 131), (30, 135), (45, 136), (58, 131), (65, 129)), {
        "wrist": (63, 122), "palm": (46, 122), "fingertip_region": (16, 121),
    }, "weak", "right_arm", "right", "Small master-image hands. Mask is only a placement guide; fingers need a separate high-detail source."),
    Part("left_leg", (250, 274, 308, 473), (
        (256, 281), (280, 280), (296, 289), (301, 326),
        (294, 362), (291, 405), (287, 440), (286, 468),
        (268, 468), (264, 434), (262, 400), (266, 359),
        (258, 324)), {
        "hip": (280, 283), "knee": (284, 379), "ankle": (278, 466),
    }, "review_only", "torso_pelvis", "left", "Viewer-right leg, hip to ankle; foot intentionally split at ankle."),
    Part("right_leg", (204, 274, 262, 473), (
        (256, 281), (232, 280), (216, 289), (211, 326),
        (218, 362), (221, 405), (225, 440), (226, 468),
        (244, 468), (248, 434), (250, 400), (246, 359),
        (254, 324)), {
        "hip": (232, 283), "knee": (228, 379), "ankle": (234, 466),
    }, "review_only", "torso_pelvis", "right", "Viewer-left leg, hip to ankle; foot intentionally split at ankle."),
    Part("left_foot", (251, 459, 309, 509), (
        (271, 461), (283, 461), (292, 473), (297, 492),
        (295, 502), (267, 503), (262, 495), (260, 483)), {
        "ankle": (278, 466), "toe_region": (287, 497),
    }, "weak", "left_leg", "left", "Small master-image foot; low-confidence depth and contour."),
    Part("right_foot", (203, 459, 261, 509), (
        (241, 461), (229, 461), (220, 473), (215, 492),
        (217, 502), (245, 503), (250, 495), (252, 483)), {
        "ankle": (234, 466), "toe_region": (225, 497),
    }, "weak", "right_leg", "right", "Small master-image foot; low-confidence depth and contour."),
)

COLOR = {
    "torso_pelvis": (255, 191, 75),
    "head": (97, 216, 141),
    "left_arm": (119, 178, 247), "right_arm": (119, 178, 247),
    "left_hand": (247, 133, 133), "right_hand": (247, 133, 133),
    "left_leg": (217, 163, 248), "right_leg": (217, 163, 248),
    "left_foot": (244, 170, 124), "right_foot": (244, 170, 124),
}

# Explicit seam pairings for later 3-D attachment design; 2-D guides only.
SEAMS = (
    ("head", "neck_joint", "torso_pelvis", "neck"),
    ("left_arm", "shoulder", "torso_pelvis", "left_shoulder"),
    ("right_arm", "shoulder", "torso_pelvis", "right_shoulder"),
    ("left_hand", "wrist", "left_arm", "wrist"),
    ("right_hand", "wrist", "right_arm", "wrist"),
    ("left_leg", "hip", "torso_pelvis", "left_hip"),
    ("right_leg", "hip", "torso_pelvis", "right_hip"),
    ("left_foot", "ankle", "left_leg", "ankle"),
    ("right_foot", "ankle", "right_leg", "ankle"),
)


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1048576), b""):
            h.update(data)
    return h.hexdigest()


def guard(master: Path, output: Path) -> None:
    if master.resolve() == output.resolve() or master.resolve().is_relative_to(output.resolve()):
        raise ValueError("Output path may not contain the source image")
    if not master.is_file():
        raise ValueError(f"Missing approved master: {master}")
    actual = file_sha(master)
    if actual != SHA256:
        raise ValueError(f"Master checksum mismatch; expected {SHA256}, got {actual}")
    with Image.open(master) as img:
        if img.size != (512, 512):
            raise ValueError(f"Expected 512x512 approved master; found {img.size}")
    for p in PARTS:
        x1, y1, x2, y2 = p.box
        if not (0 <= x1 < x2 <= 512 and 0 <= y1 < y2 <= 512):
            raise ValueError(f"Invalid bounds: {p.name}")
        for k, (x, y) in p.anchors.items():
            if not (x1 <= x < x2 and y1 <= y < y2):
                raise ValueError(f"Anchor {p.name}.{k} falls outside crop")
    ids = {p.name for p in PARTS}
    for a, _, b, _ in SEAMS:
        if a not in ids or b not in ids:
            raise ValueError("Unknown seam component")


def prepare_image(img: Image.Image, p: Part, out: Path) -> dict:
    x1, y1, x2, y2 = p.box
    crop = img.crop(p.box)
    crop.save(out / f"{p.name}_crop.png")

    mask = Image.new("L", (x2 - x1, y2 - y1), 0)
    d = ImageDraw.Draw(mask)
    points = [(x - x1, y - y1) for x, y in p.polygon]
    d.polygon(points, fill=255)
    mask.save(out / f"{p.name}_mask.png")

    # Matte is deliberately coarse. It must be approved/corrected before use
    # as a segmentation mask or as 3D model conditioning input.
    rgba = crop.convert("RGBA")
    rgba.putalpha(mask)
    rgba.save(out / f"{p.name}_guide.png")
    return {
        "id": p.name, "parent": p.parent, "anatomical_side": p.side,
        "bbox_master_xyxy": list(p.box),
        "mask_polygon_master": [list(point) for point in p.polygon],
        "anchors_master_xy": {k: list(v) for k, v in p.anchors.items()},
        "anchors_local_xy": {k: [v[0] - x1, v[1] - y1] for k, v in p.anchors.items()},
        "crop": f"{p.name}_crop.png", "coarse_mask": f"{p.name}_mask.png",
        "guide": f"{p.name}_guide.png", "readiness": p.readiness,
        "detail": p.detail,
        "approved_for_inference": False,
    }


def master_review(img: Image.Image, output: Path) -> None:
    # Draw labels in a separate legend instead of stacking them on the image.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for p in PARTS:
        color = COLOR[p.name]
        draw.line([*p.polygon, p.polygon[0]], fill=(*color, 230), width=2)
        for ax, ay in p.anchors.values():
            draw.ellipse((ax - 2, ay - 2, ax + 2, ay + 2), fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
    Image.alpha_composite(img.convert("RGBA"), overlay).save(output / "master_seams.png")


def review_html(output: Path, manifest: dict) -> None:
    cards = []
    for p in manifest["parts"]:
        ident = html.escape(p["id"])
        card = f"""
        <article>
          <h3>{ident} <small>{html.escape(p['readiness'])}</small></h3>
          <div class='pair'>
            <figure><img src='{ident}_crop.png'><figcaption>Raw crop</figcaption></figure>
            <figure><img src='{ident}_guide.png' class='cutout'><figcaption>Coarse masked guide</figcaption></figure>
          </div>
          <p>Bounds: {p['bbox_master_xyxy']} · Anchors: {', '.join(p['anchors_master_xy'])}</p>
          <p>{html.escape(p['detail'])}</p>
        </article>"""
        cards.append(card)
    seams = "".join(f"<li><code>{html.escape(a)}.{html.escape(ka)}</code> ⇄ <code>{html.escape(b)}.{html.escape(kb)}</code></li>" for a,ka,b,kb in manifest["seams"])
    content = "\n".join(cards)
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Mara seam-aware reference review</title>
    <style>body{{font:15px system-ui,sans-serif;background:#111923;color:#e3edf7;margin:24px auto;max-width:1400px;padding:0 15px}}p{{line-height:1.5}}h1{{margin:0}}small{{font-weight:normal;color:#ffcd83}}.banner{{background:#26384a;padding:12px;border-radius:8px}}.master{{width:min(512px,100%);height:auto;background:#ccc}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}}article{{background:#1d2a39;border:1px solid #354457;padding:14px;border-radius:9px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}figure{{margin:0;min-width:0}}figure img{{display:block;width:100%;height:185px;object-fit:contain;background:#c8c8c8}}figure img.cutout{{background-color:#dce4eb;background-image:linear-gradient(45deg,#aaa 25%,transparent 25%),linear-gradient(-45deg,#aaa 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#aaa 75%),linear-gradient(-45deg,transparent 75%,#aaa 75%);background-size:16px 16px;background-position:0 0,0 8px,8px -8px,-8px 0}}figcaption{{font-size:12px;color:#b6c7d9}}code{{color:#ffd18c}}li{{margin:4px 0}}</style></head><body>
    <h1>Mara — seam-aware reference review</h1><p class='banner'><b>NOT reconstruction-ready.</b> Polygon masks and joint anchors are approximate 2-D design guides. The approved master is unchanged; generation lock remains enforced. Anatomical left is the viewer's right.</p>
    <h2>Original master with landmarks and boundaries</h2><img class='master' src='master_seams.png' alt='Mara with polygon guides'><p>Full SHA-256: <code>{manifest['master_sha256']}</code></p>
    <h2>Joint pairings (2-D only)</h2><ul>{seams}</ul>
    <h2>Parts</h2><section class='grid'>{content}</section></body></html>"""
    (output / "review.html").write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--input", type=Path, default=MASTER)
    a.add_argument("--output", type=Path, default=OUT)
    a.add_argument("--dry-run", action="store_true")
    args = a.parse_args(argv)
    try:
        guard(args.input, args.output)
        if args.output.exists():
            raise ValueError(f"Output directory exists; choose a new --output path: {args.output}")
        print(f"Verified approved master: {args.input}")
        print(f"Plan: {len(PARTS)} tighter anatomical crops, coarse masks, and {len(SEAMS)} seam pairs")
        if args.dry_run:
            print(f"Would write: {args.output}")
            return 0
        args.output.mkdir(parents=True, exist_ok=False)
        with Image.open(args.input) as source:
            img = source.convert("RGB")
        data = [prepare_image(img, part, args.output) for part in PARTS]
        manifest = {
            "version": 2,
            "purpose": "review_only",
            "generation_locked": True,
            "master": str(args.input),
            "master_sha256": SHA256,
            "coord_system": {"origin": "top_left", "x": "image_right", "y": "image_down", "anatomical_left": "viewer_right", "units": "pixels"},
            "notices": [
                "All polygons and anchors are approximate, not detected or calibrated.",
                "Mask regions may include background, miss edges, or overlap other parts.",
                "Seam pairs are shared 2-D positions, not 3-D attachment frames.",
                "Never infer geometry quality from enlarged tiny crops.",
                "Use independent detailed references for hands and feet.",
            ],
            "seams": [list(s) for s in SEAMS],
            "parts": data,
        }
        master_review(img, args.output)
        (args.output / "reference_parts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        review_html(args.output, manifest)
        print(f"Created {args.output / 'reference_parts.json'}")
        print(f"Open {args.output / 'review.html'}")
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
