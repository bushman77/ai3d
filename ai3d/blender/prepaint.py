"""Prepare a raw Hunyuan shape for Paint3D (run inside Blender).

blender --background --factory-startup --python-exit-code 1 \
  --python ai3d/blender/prepaint.py -- --input 03_shape.glb \
  --output 04_paint_mesh.glb --target-faces 40000

Joins parts, welds duplicate vertices, deletes tiny loose islands, reduces to
the target triangle count, recalculates normals. No materials are exported.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
import bmesh  # noqa: E402  (after bpy: the pip bpy module provides it)

from common import (  # noqa: E402
    export_glb, import_glb, join_meshes, reset_scene, script_args, select_only,
    triangle_count, write_json,
)


def remove_small_islands(obj, keep_fraction: float = 0.002) -> int:
    """Delete disconnected pieces smaller than keep_fraction of all faces."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for face in bm.faces:
        if face.index in seen:
            continue
        stack, island = [face], []
        seen.add(face.index)
        while stack:
            f = stack.pop()
            island.append(f)
            for edge in f.edges:
                for g in edge.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        islands.append(island)
    total = len(bm.faces)
    doomed = [f for isl in islands if len(isl) < total * keep_fraction for f in isl]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()
    return sum(1 for isl in islands if len(isl) < total * keep_fraction)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--target-faces", type=int, default=40000)
    p.add_argument("--stats", type=Path)
    a = p.parse_args(script_args())

    reset_scene()
    obj = join_meshes(import_glb(a.input), "AI3D_PAINT_MESH")
    obj.data.materials.clear()
    before = triangle_count(obj)
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.delete_loose()
    bpy.ops.object.mode_set(mode="OBJECT")
    removed = remove_small_islands(obj)

    tris = triangle_count(obj)
    if tris > a.target_faces:
        mod = obj.modifiers.new("ai3d_decimate", "DECIMATE")
        mod.ratio = a.target_faces / tris
        bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.shade_smooth()

    export_glb(a.output, [obj])
    stats = {"input_triangles": before, "output_triangles": triangle_count(obj),
             "removed_islands": removed}
    print("[prepaint]", stats, flush=True)
    if a.stats:
        write_json(a.stats, stats)


if __name__ == "__main__":
    main()
