#!/usr/bin/env python3
"""Create non-destructive visual review crops from Mara's approved master PNG.

This deliberately does not synthesize, mask, inpaint, or create model-ready
single-part references. It only prepares evidence for human landmark review.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys

APPROVED_SHA256 = "144d06916502ecb524e4113f8bc11b9ab80bfa6714290773a7046d23bd4e2791"
EXPECTED_SIZE = (512, 512)
# Coordinates are approximate bounding rectangles manually estimated from the
# approved full-body frontal image. Left/right refer to Mara, not the viewer.
CROPS = [
    ("torso_pelvis", (196, 63, 319, 290)),
    ("head", (215, 10, 290, 91)),
    ("left_arm", (285, 96, 454, 157)),
    ("right_arm", (59, 96, 227, 157)),
    ("left_hand", (432, 99, 500, 151)),
    ("right_hand", (11, 99, 82, 151)),
    ("left_leg", (250, 250, 308, 486)),
    ("right_leg", (197, 250, 258, 486)),
    ("left_foot", (252, 455, 308, 509)),
    ("right_foot", (201, 455, 255, 509)),
]


def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def verify_image(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"Missing or symlinked approved master: {path}")
    sha = fingerprint(path)
    if sha != APPROVED_SHA256:
        raise RuntimeError(f"Master checksum mismatch: {sha}; refusing to process")
    with path.open("rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Master does not have a PNG signature")
        f.seek(16)
        wh = f.read(8)
    size = (int.from_bytes(wh[:4], 'big'), int.from_bytes(wh[4:], 'big'))
    if size != EXPECTED_SIZE:
        raise RuntimeError(f"Expected {EXPECTED_SIZE} approved image, got {size}")


def run(master: Path, dest: Path, dry_run: bool) -> None:
    verify_image(master)
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise RuntimeError("Output directory must not be a symlink or non-directory")
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"Nonempty output directory already exists: {dest}. Use a new path.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg and not dry_run:
        raise RuntimeError("ffmpeg not found on PATH")
    print(f"Approved master VERIFIED: {master} ({APPROVED_SHA256[:12]}…)")
    print("Anatomical left = viewer's RIGHT; anatomical right = viewer's LEFT")
    for part, (x0,y0,x1,y1) in CROPS:
        print(f"  {part:<14} x={x0:3}..{x1:3} y={y0:3}..{y1:3} (review crop only)")
    print(f"Output: {dest}")
    if dry_run:
        print("DRY RUN: no changes made")
        return
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(master, dest / "master.png")
    entries = []
    for part, (x0, y0, x1, y1) in CROPS:
        name = f"{part}.png"
        filter_str = f"crop={x1-x0}:{y1-y0}:{x0}:{y0}"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(master),
                        "-vf", filter_str, "-frames:v", "1", "-y", str(dest / name)], check=True)
        entries.append({"id": part, "png": name, "bounds_xyxy": [x0,y0,x1,y1],
                        "crop_role": "review_only_not_isolated_or_model_ready"})
    manifest = {
        "version": 1,
        "master_source": str(master.resolve()),
        "approved_sha256": APPROVED_SHA256,
        "dimensions": [512, 512],
        "left_right_convention": "anatomical: image-left = character-right",
        "status": "human_review_required",
        "warnings": [
            "Rectangular crops contain background and may include adjacent anatomy.",
            "Image resolution is inadequate for detailed head, fingers, and feet reconstruction.",
            "These are visual review crops; do not feed them directly to Hunyuan.",
            "Component segmentation, consistent depth/view generation, fitting and mesh quality gates remain unimplemented."
        ],
        "crops": entries,
    }
    (dest / "review_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    cards = "\n".join(
        f'<article><h3>{html.escape(e["id"])}</h3><img src="{e["png"]}" alt="{e["id"]}">'
        f'<p>Rectangle {e["bounds_xyxy"]}</p></article>'
        for e in entries
    )
    (dest / "review.html").write_text('''<!doctype html><html><head><meta charset="utf-8">
<title>Mara approved-image crop review</title><style>
body{font:16px system-ui;background:#20252b;color:#edf1f6;margin:2rem}
strong{color:#e6bb77}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
article{background:#303941;padding:16px;border-radius:12px}img{image-rendering:auto;max-width:100%;object-fit:contain;background:#969696}
article img{width:100%;height:230px}h3{margin:.1rem 0 .75rem}p{color:#bcc7d1}
</style></head><body>
<h1>Mara Venn — approved master crop review</h1>
<p><strong>Not reconstruction inputs.</strong> Rectangles are approximate and include background/other anatomy. Anatomical left is viewer's right.</p>
<img src="master.png" width="512" height="512" alt="Approved master" />
<h2>Independent part regions</h2><section class="gallery">''' + cards + '''</section></body></html>''')
    print(f"Created {len(entries)} review crops and {dest / 'review.html'}")
    print("GPU generation remains LOCKED. Review boundaries before implementing segmentation.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, default=Path('approved_references/mara_body_front_approved.png'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/mara_reference_review_v1'))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        run(args.master, args.output_dir, args.dry_run)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
