#!/usr/bin/env python3
"""Background removal (runs in the Hunyuan3D-2 virtualenv: hy3dgen.rembg).

cutout.py INPUT OUTPUT [auto|skip]
Images that already have transparency are kept as they are.
"""
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


if __name__ == "__main__":
    main(*sys.argv[1:4])
