"""Measure a finished asset and render review images (run inside Blender).

blender --background --factory-startup --python-exit-code 1 \
  --python ai3d/blender/quality.py -- --mesh 06_game.glb \
  --cutout 02_cutout.png --previews previews/ --stats quality_game.json

Numbers instead of eyeballing:
* mesh: triangles, separate pieces, holes (boundary edges), non-manifold
  edges, UVs, texture count;
* silhouette_iou: how well the mesh's front outline matches the cutout
  (1.0 = identical outline, < 0.8 usually means a wrong or broken shape);
* rig (when the GLB has a skin): bone count, and preview renders of the
  test action so bad weights are visible at a glance.
"""
import argparse
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

from common import import_glb, reset_scene, script_args, write_json  # noqa: E402

try:
    import numpy as np  # bundled with Blender
except ImportError:  # pragma: no cover
    np = None


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--mesh", type=Path, required=True)
    p.add_argument("--cutout", type=Path)
    p.add_argument("--previews", type=Path, help="Folder for PNG renders (omit to skip)")
    p.add_argument("--preview-size", type=int, default=512)
    p.add_argument("--grid", type=int, default=160, help="Silhouette resolution")
    p.add_argument("--frames", default="20,40,60,80", help="Test-action frames to render for rigs")
    p.add_argument("--stats", type=Path, required=True)
    return p.parse_args(script_args())


def mesh_stats(objs):
    bm = bmesh.new()
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in objs:
        tmp = obj.evaluated_get(deps).to_mesh()
        tmp.transform(obj.matrix_world)
        bm.from_mesh(tmp)
        obj.evaluated_get(deps).to_mesh_clear()
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    # connected pieces
    bm.verts.ensure_lookup_table()
    seen, pieces = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        pieces += 1
        stack = [v]
        seen.add(v.index)
        while stack:
            x = stack.pop()
            for e in x.link_edges:
                w = e.other_vert(x)
                if w.index not in seen:
                    seen.add(w.index)
                    stack.append(w)
    verts = len(bm.verts)
    bm.free()
    return {"triangles": tris, "vertices": verts, "pieces": pieces,
            "boundary_edges": boundary, "non_manifold_edges": non_manifold}


def bounds(objs):
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for obj in objs:
        ev = obj.evaluated_get(deps)
        tmp = ev.to_mesh()
        pts += [ev.matrix_world @ v.co for v in tmp.vertices]
        ev.to_mesh_clear()
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def mesh_silhouette(objs, grid):
    deps = bpy.context.evaluated_depsgraph_get()
    trees = [BVHTree.FromObject(o, deps) for o in objs]
    lo, hi = bounds(objs)
    h = grid
    w = max(1, round(grid * (hi.x - lo.x) / max(1e-6, hi.z - lo.z)))
    mask = np.zeros((h, w), dtype=bool)
    start_y = lo.y - 1.0
    direction = Vector((0, 1, 0))
    dist = (hi.y - lo.y) + 2.0
    for r in range(h):
        z = hi.z - (r + 0.5) * (hi.z - lo.z) / h
        for c in range(w):
            x = lo.x + (c + 0.5) * (hi.x - lo.x) / w
            origin = Vector((x, start_y, z))
            mask[r, c] = any(t.ray_cast(origin, direction, dist)[0] is not None for t in trees)
    return mask


def image_silhouette(path, shape):
    img = bpy.data.images.load(str(path))
    W, H = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, img.channels)
    alpha = px[::-1, :, 3] > 0.5 if img.channels == 4 else px[::-1, :, :3].mean(axis=2) < 0.95
    rows, cols = np.where(alpha)
    if rows.size == 0:
        return None
    crop = alpha[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    h, w = shape
    ri = (np.arange(h) + 0.5) * crop.shape[0] / h
    ci = (np.arange(w) + 0.5) * crop.shape[1] / w
    return crop[ri.astype(int)[:, None], ci.astype(int)[None, :]]


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


def setup_render(size):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("ai3d_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.6, 0.6, 0.62, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
    scene.world = world
    sun = bpy.data.objects.new("ai3d_sun", bpy.data.lights.new("ai3d_sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    scene.collection.objects.link(sun)
    cam = bpy.data.objects.new("ai3d_cam", bpy.data.cameras.new("ai3d_cam"))
    cam.data.type = "ORTHO"
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def render_view(cam, objs, view, path):
    lo, hi = bounds(objs)
    mid = (lo + hi) / 2
    span = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z) * 1.1
    cam.data.ortho_scale = span
    d = span * 2
    placements = {
        "front": (Vector((mid.x, mid.y - d, mid.z)), (math.radians(90), 0, 0)),
        "back": (Vector((mid.x, mid.y + d, mid.z)), (math.radians(90), 0, math.radians(180))),
        "side": (Vector((mid.x + d, mid.y, mid.z)), (math.radians(90), 0, math.radians(90))),
        "threequarter": (mid + Vector((d * 0.7, -d * 0.7, 0)), (math.radians(90), 0, math.radians(45))),
    }
    cam.location, cam.rotation_euler = placements[view]
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    a = parse()
    reset_scene()
    imported = import_glb(a.mesh)
    armatures = [o for o in imported if o.type == "ARMATURE"]
    # The glTF importer adds a bone-display mesh for skinned files; skip it.
    shapes = {pb.custom_shape for arm in armatures for pb in arm.pose.bones if pb.custom_shape}
    meshes = [o for o in imported if o.type == "MESH" and o not in shapes]
    stats = {"file": str(a.mesh), "mesh": mesh_stats(meshes)}
    stats["mesh"]["uv"] = all(o.data.uv_layers for o in meshes)
    stats["mesh"]["images"] = len([i for i in bpy.data.images if i.size[0] > 0])
    lo, hi = bounds(meshes)
    stats["mesh"]["size_m"] = [round(v, 4) for v in (hi - lo)]

    if a.cutout and a.cutout.is_file() and np is not None:
        sil = mesh_silhouette(meshes, a.grid)
        ref = image_silhouette(a.cutout, sil.shape)
        if ref is not None:
            front = iou(sil, ref)
            mirrored = iou(sil[:, ::-1], ref)
            stats["silhouette_iou"] = round(max(front, mirrored), 4)
            stats["silhouette_mirrored_better"] = mirrored > front + 0.02

    if armatures:
        arm = armatures[0]
        stats["rig"] = {
            "bones": len(arm.data.bones),
            "actions": [act.name for act in bpy.data.actions],
        }

    if a.previews:
        a.previews.mkdir(parents=True, exist_ok=True)
        cam = setup_render(a.preview_size)
        stem = a.mesh.stem
        rendered = []
        if armatures and bpy.data.actions:
            arm = armatures[0]
            if arm.animation_data is None:
                arm.animation_data_create()
            arm.animation_data.action = bpy.data.actions[0]
            frames = [int(f) for f in a.frames.split(",") if f.strip()]
            for f in frames:
                bpy.context.scene.frame_set(f)
                out = a.previews / f"{stem}_pose{f:03d}.png"
                render_view(cam, meshes, "threequarter", out)
                rendered.append(out.name)
            bpy.context.scene.frame_set(0)
        for view in ("front", "side", "back"):
            out = a.previews / f"{stem}_{view}.png"
            render_view(cam, meshes, view, out)
            rendered.append(out.name)
        stats["previews"] = rendered

    print("[quality]", stats, flush=True)
    write_json(a.stats, stats)


if __name__ == "__main__":
    main()
