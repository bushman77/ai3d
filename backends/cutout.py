#!/usr/bin/env python3
"""Background removal (runs in the Hunyuan3D-2 virtualenv: hy3dgen.rembg).

cutout.py INPUT OUTPUT [auto|skip]
Images that already have transparency are kept as they are.
"""
import json
from pathlib import Path
import sys

from PIL import Image


def main(src, dst, mode="auto"):
    im = Image.open(src)
    alpha = im.convert("RGBA").getchannel("A")
    if alpha.getextrema()[0] < 250 or mode == "skip":
        out = im.convert("RGBA")
        print("[cutout] using existing alpha", flush=True)
    else:
        from hy3dgen.rembg import BackgroundRemover
        print("[cutout] removing background", flush=True)
        out = BackgroundRemover()(im.convert("RGB"))
    out.save(dst)
    print("[cutout]", dst, "alpha", out.getchannel("A").getextrema(), "size", out.size, flush=True)
    # Sidecar: where the figure is and whether it touches the picture edge
    # (a cropped head or feet makes the shape and the projection wrong).
    a = out.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    box = a.getbbox()
    w, h = out.size
    touches = []
    if box:
        x0, y0, x1, y1 = box
        touches = [edge for edge, hit in (("top", y0 <= 1), ("bottom", y1 >= h - 1),
                                          ("left", x0 <= 1), ("right", x1 >= w - 1)) if hit]
    info = {"size": [w, h], "bbox": list(box) if box else None, "touches": touches}
    Path(dst).with_suffix(".json").write_text(json.dumps(info) + "\n")
    if touches:
        print(f"[cutout] WARNING: figure touches the {', '.join(touches)} edge "
              "(cut off?)", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
