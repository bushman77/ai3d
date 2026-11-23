#!/usr/bin/env python3
"""Hunyuan3D-2 shape generation, single-view or multi-view.

Runs inside the Hunyuan3D-2 virtualenv (it imports hy3dgen and torch);
AI3D calls it as a subprocess, so the host never imports CUDA code.
This file is tracked in ai3d, replacing the untracked first_mesh.py that
used to live inside the Hunyuan checkout.

Single view:  --front cutout.png
Multi-view:   --front f.png --left l.png --back b.png [--right r.png]
"""
import argparse
from pathlib import Path
import sys
import time

MODELS = {
    # name: (default Hugging Face repo, subfolder, multiview, turbo)
    "mini": ("tencent/Hunyuan3D-2mini", "hunyuan3d-dit-v2-mini", False, False),
    "mini-turbo": ("tencent/Hunyuan3D-2mini", "hunyuan3d-dit-v2-mini-turbo", False, True),
    "mv": ("tencent/Hunyuan3D-2mv", "hunyuan3d-dit-v2-mv", True, False),
    "mv-turbo": ("tencent/Hunyuan3D-2mv", "hunyuan3d-dit-v2-mv-turbo", True, True),
}
VIEWS = ("front", "left", "back", "right")


def parse():
    p = argparse.ArgumentParser(description=__doc__)
    for view in VIEWS:
        p.add_argument(f"--{view}", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", choices=sorted(MODELS), default="mini")
    p.add_argument("--model-path", default=None,
                   help="Local model folder (containing the subfolder) or Hugging Face repo id")
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--octree-resolution", type=int, default=256)
    p.add_argument("--num-chunks", type=int, default=8000)
    p.add_argument("--guidance-scale", type=float, default=5.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--keep-floaters", action="store_true")
    p.add_argument("--low-vram", action="store_true",
                   help="Keep only the diffusion model on the GPU while sampling: the image "
                        "encoder leaves the GPU after encoding, the shape decoder joins it "
                        "only after sampling (saves ~1 GB)")
    a = p.parse_args()
    if a.front is None:
        p.error("--front is required")
    if a.steps < 1 or a.octree_resolution < 64 or a.num_chunks < 1:
        p.error("invalid steps/octree/chunks")
    multiview = MODELS[a.model][2]
    extra = [v for v in ("left", "back", "right") if getattr(a, v)]
    if extra and not multiview:
        p.error(f"model {a.model} is single-view; use mv or mv-turbo with side/back views")
    if multiview and not extra:
        p.error(f"model {a.model} needs at least one of --left/--back/--right")
    for view in VIEWS:
        path = getattr(a, view)
        if path is not None and not path.is_file():
            p.error(f"{view} image not found: {path}")
    if a.output.suffix.lower() != ".glb":
        p.error("--output must be a .glb")
    return a


def enable_low_vram(pipe, torch):
    """Swap pipeline parts on/off the GPU around the sampling loop.

    pipe.device stays cuda (latents and conditions are created there); only the
    modules move. Wraps encode_cond and _export, which __call__ looks up on the
    instance.
    """
    pipe.vae.to("cpu")
    torch.cuda.empty_cache()
    encode_cond, export = pipe.encode_cond, pipe._export

    def encode_then_free(*args, **kwargs):
        out = encode_cond(*args, **kwargs)
        pipe.conditioner.to("cpu")
        torch.cuda.empty_cache()
        print(f"[shape] low-vram: encoder off GPU, "
              f"{torch.cuda.memory_allocated() / 2**30:.2f} GiB in use for sampling", flush=True)
        return out

    def free_then_export(*args, **kwargs):
        pipe.model.to("cpu")
        torch.cuda.empty_cache()
        pipe.vae.to("cuda")
        return export(*args, **kwargs)

    pipe.encode_cond = encode_then_free
    pipe._export = free_then_export
    print("[shape] low-vram mode on", flush=True)


def main():
    a = parse()
    import torch
    from PIL import Image
    from hy3dgen.shapegen import (
        DegenerateFaceRemover, FloaterRemover, Hunyuan3DDiTFlowMatchingPipeline,
    )

    repo, subfolder, multiview, turbo = MODELS[a.model]
    source = str(Path(a.model_path).expanduser()) if a.model_path else repo
    print(f"[shape] model={a.model} source={source}/{subfolder} steps={a.steps} "
          f"octree={a.octree_resolution} chunks={a.num_chunks} seed={a.seed}", flush=True)
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        source, subfolder=subfolder, use_safetensors=True, device="cuda",
    )
    if turbo and hasattr(pipe, "enable_flashvdm"):
        pipe.enable_flashvdm()

    if a.low_vram:
        enable_low_vram(pipe, torch)

    if multiview:
        image = {v: Image.open(getattr(a, v)).convert("RGBA") for v in VIEWS if getattr(a, v)}
        print("[shape] views:", ", ".join(image), flush=True)
    else:
        image = Image.open(a.front).convert("RGBA")

    start = time.monotonic()
    with torch.inference_mode():
        mesh = pipe(
            image=image,
            num_inference_steps=a.steps,
            octree_resolution=a.octree_resolution,
            num_chunks=a.num_chunks,
            guidance_scale=a.guidance_scale,
            generator=torch.manual_seed(a.seed),
            output_type="trimesh",
        )[0]
    raw_faces = len(mesh.faces)
    if not a.keep_floaters:
        mesh = FloaterRemover()(mesh)
        mesh = DegenerateFaceRemover()(mesh)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(a.output))
    print(f"[shape] wrote {a.output}: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces "
          f"(raw {raw_faces}) in {time.monotonic() - start:.0f}s", flush=True)
    if torch.cuda.is_available():
        print(f"[shape] peak VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
