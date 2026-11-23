#!/usr/bin/env python3
"""Isolated high-detail Hunyuan3D-2mini reconstruction, per-component controls.

Run using Hunyuan3D-2/.venv/bin/python. Does not modify upstream checkout.
"""
import argparse
from pathlib import Path
import torch
from PIL import Image
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model-dir', type=Path, required=True)
    p.add_argument('--steps', type=int, default=50)
    p.add_argument('--octree-resolution', type=int, default=256)
    p.add_argument('--chunks', type=int, default=4000)
    p.add_argument('--seed', type=int, default=12345)
    a = p.parse_args()
    if a.steps <= 0 or a.octree_resolution < 32 or a.chunks < 1:
        p.error('Invalid reconstruction settings')
    if not a.input.is_file():
        p.error(f'Reference not found: {a.input}')
    if a.output.suffix != '.glb' or a.output.exists():
        p.error('Output must be a NEW .glb file; no overwriting approved meshes')
    if not a.model_dir.is_dir():
        p.error(f'Model directory not found: {a.model_dir}')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    print(f'[HUNYUAN DETAIL] steps={a.steps}, octree={a.octree_resolution}, chunks={a.chunks}, seed={a.seed}', flush=True)
    image = Image.open(a.input).convert('RGBA')
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(a.model_dir), subfolder='hunyuan3d-dit-v2-mini',
        use_safetensors=True, device='cuda'
    )
    with torch.inference_mode():
        mesh = pipe(
            image=image,
            num_inference_steps=a.steps,
            octree_resolution=a.octree_resolution,
            num_chunks=a.chunks,
            generator=torch.manual_seed(a.seed),
            output_type='trimesh'
        )[0]
    mesh.export(str(a.output))
    print('SUCCESS:', a.output)
    print('Vertices:', len(mesh.vertices))
    print('Faces:', len(mesh.faces))


if __name__ == '__main__':
    main()
