"""Clean low-poly game mesh with baked textures (run inside Blender).

blender --background --factory-startup --python-exit-code 1 \
  --python ai3d/blender/retopo_bake.py -- --input 05_painted.glb \
  --output 06_game.glb --target-faces 8000

1. Joins the painted high-poly mesh (keeps its material) -> HIGH.
2. Copies it and voxel-remeshes the copy: one watertight shell, no
   overlapping parts (this is what makes automatic rig weights work).
3. QuadriFlow quad remesh to --target-faces quads (fallback: decimate).
4. Shrinkwraps the low mesh back onto HIGH, unwraps fresh UVs.
5. Cycles bakes HIGH -> LOW: base colour, tangent-space normal, roughness.
6. Exports only LOW, with the baked PNGs embedded; writes stats JSON.
"""
import argparse
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

from common import (  # noqa: E402
    export_glb, import_glb, join_meshes, reset_scene, script_args, select_only,
    triangle_count, write_json,
)


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--target-faces", type=int, default=8000, help="Quad faces for QuadriFlow")
    p.add_argument("--method", choices=("quadriflow", "decimate"), default="quadriflow")
    p.add_argument("--voxel-ratio", type=float, default=0.004,
                   help="Voxel size as a fraction of the model height")
    p.add_argument("--texture-size", type=int, default=2048)
    p.add_argument("--samples", type=int, default=4)
    p.add_argument("--cage-ratio", type=float, default=0.012,
                   help="Bake ray distance as a fraction of the model height")
    p.add_argument("--device", choices=("CPU", "GPU"), default="CPU")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--stats", type=Path)
    a = p.parse_args(script_args())
    if a.target_faces < 100 or a.texture_size < 64:
        p.error("target-faces must be >= 100 and texture-size >= 64")
    if a.input.resolve() == a.output.resolve():
        p.error("output must differ from input")
    return a


def duplicate(obj, name):
    copy = obj.copy()
    copy.data = obj.data.copy()
    copy.name = copy.data.name = name
    bpy.context.collection.objects.link(copy)
    return copy


def voxel_remesh(obj, size):
    obj.data.remesh_voxel_size = size
    obj.data.remesh_voxel_adaptivity = 0.0
    select_only([obj])
    bpy.ops.object.voxel_remesh()


def non_manifold_count(obj):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bad = sum(1 for e in bm.edges if not e.is_manifold) + sum(1 for v in bm.verts if not v.is_manifold)
    bm.free()
    return bad


def make_manifold(obj, rounds=4):
    """Remove the pinched vertices/edges voxel remesh leaves where thin parts touch.

    Also collapses near-zero-length edges: QuadriFlow refuses any mesh with an
    edge shorter than 1e-4, and voxel remesh produces a few of those.
    """
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.dissolve_degenerate(threshold=2e-4)
    bpy.ops.object.mode_set(mode="OBJECT")
    for _ in range(rounds):
        if non_manifold_count(obj) == 0:
            # QuadriFlow also rejects inconsistent face winding.
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode="OBJECT")
            break
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold(extend=False, use_wire=True, use_boundary=False,
                                         use_multi_face=True, use_non_contiguous=True, use_verts=True)
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.delete_loose()
        bpy.ops.mesh.fill_holes(sides=0)
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    return non_manifold_count(obj)


def decimate_to(obj, triangles):
    tris = triangle_count(obj)
    if tris > triangles:
        select_only([obj])
        mod = obj.modifiers.new("ai3d_decimate", "DECIMATE")
        mod.ratio = triangles / tris
        bpy.ops.object.modifier_apply(modifier=mod.name)


def quadriflow(obj, faces, seed):
    select_only([obj])
    before = len(obj.data.polygons)
    try:
        result = bpy.ops.object.quadriflow_remesh(
            target_faces=faces, use_mesh_symmetry=False, use_preserve_sharp=False,
            use_preserve_boundary=False, preserve_attributes=False,
            smooth_normals=False, mode="FACES", seed=seed,
        )
    except RuntimeError as exc:
        print("[retopo] QuadriFlow error:", str(exc).strip(), flush=True)
        return False
    after = len(obj.data.polygons)
    ok = "FINISHED" in result and after > 0 and after != before
    if not ok:
        print(f"[retopo] QuadriFlow did not change the mesh ({result}, {before}->{after})", flush=True)
    return ok


def shrinkwrap(obj, target):
    select_only([obj])
    mod = obj.modifiers.new("ai3d_shrinkwrap", "SHRINKWRAP")
    mod.target = target
    mod.wrap_method = "NEAREST_SURFACEPOINT"
    bpy.ops.object.modifier_apply(modifier=mod.name)


def unwrap(obj):
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.uv.pack_islands(margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")


def new_image(name, size, colour, non_color):
    img = bpy.data.images.new(name, size, size, alpha=False)
    img.generated_color = colour
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def surface_distance(low, high, height):
    """Mean / max distance (fraction of height) from the voxel shell to LOW.

    Measures detail lost by the low-poly mesh (0 = identical surface).
    """
    deps = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(low, deps)
    dists = []
    mw = high.matrix_world
    for v in high.data.vertices:
        hit = tree.find_nearest(mw @ v.co)
        if hit[0] is not None:
            dists.append(hit[3])
    if not dists:
        return None, None
    return sum(dists) / len(dists) / height, max(dists) / height


def main():
    a = parse()
    t0 = time.monotonic()
    reset_scene()
    high = join_meshes(import_glb(a.input), "AI3D_HIGH")
    height = max(high.dimensions) or 1.0
    high_tris = triangle_count(high)

    # Fine voxel shell: the outer surface only (no inner, overlapping shells).
    # It is the shrinkwrap target and the reference for the error metric.
    shell = duplicate(high, "AI3D_SHELL")
    shell.data.materials.clear()
    voxel = a.voxel_ratio * height
    voxel_remesh(shell, voxel)
    voxel_faces = len(shell.data.polygons)
    area = sum(p.area for p in shell.data.polygons)

    method = a.method
    attempts = []
    low = None
    if method == "quadriflow":
        # QuadriFlow rejects fine voxel meshes where thin parts touch, and the
        # result is coarse anyway, so feed it a voxel size near half the
        # expected quad edge; coarsen and retry if it still refuses.
        edge = math.sqrt(area / a.target_faces)
        size = max(voxel, edge * 0.5)
        for _ in range(4):
            candidate = duplicate(high, "AI3D_LOW")
            candidate.data.materials.clear()
            voxel_remesh(candidate, size)
            make_manifold(candidate)
            ok = quadriflow(candidate, a.target_faces, a.seed)
            attempts.append({"voxel_m": round(size, 5), "ok": ok})
            if ok:
                low = candidate
                break
            bpy.data.objects.remove(candidate, do_unlink=True)
            size *= 1.5
        if low is None:
            print("[retopo] QuadriFlow refused every attempt; falling back to decimate", flush=True)
            method = "decimate (quadriflow failed)"
    if low is None:
        low = duplicate(shell, "AI3D_LOW")
        leftover = make_manifold(low)
        if leftover:
            print(f"[retopo] {leftover} non-manifold elements remain after cleanup", flush=True)
        decimate_to(low, a.target_faces * 2)
    shrinkwrap(low, shell)
    select_only([low])
    bpy.ops.object.shade_smooth()
    unwrap(low)

    # --- bake setup -------------------------------------------------------
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = a.device
    scene.cycles.samples = a.samples
    bake = scene.render.bake
    bake.use_selected_to_active = True
    bake.cage_extrusion = a.cage_ratio * height
    bake.max_ray_distance = a.cage_ratio * height * 4
    bake.margin = 16

    size = a.texture_size
    images = {
        "basecolor": new_image("ai3d_basecolor", size, (0.5, 0.5, 0.5, 1), False),
        "normal": new_image("ai3d_normal", size, (0.5, 0.5, 1.0, 1), True),
        "roughness": new_image("ai3d_roughness", size, (0.7, 0.7, 0.7, 1), True),
    }
    mat = bpy.data.materials.new("AI3D_GAME")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    tex = {}
    for i, (key, img) in enumerate(images.items()):
        node = nodes.new("ShaderNodeTexImage")
        node.image = img
        node.location = (-700, 300 - i * 300)
        tex[key] = node
    low.data.materials.append(mat)

    passes = (
        ("basecolor", "DIFFUSE", {"pass_filter": {"COLOR"}}),
        ("normal", "NORMAL", {"normal_space": "TANGENT"}),
        ("roughness", "ROUGHNESS", {}),
    )
    baked = {}
    select_only([high, low], active=low)
    for key, bake_type, extra in passes:
        nodes.active = tex[key]
        start = time.monotonic()
        try:
            bpy.ops.object.bake(type=bake_type, **extra)
            baked[key] = round(time.monotonic() - start, 1)
            print(f"[bake] {key}: {baked[key]}s", flush=True)
        except RuntimeError as exc:
            print(f"[bake] {key} failed: {exc}", flush=True)
            if key == "basecolor":
                raise

    tex_dir = a.output.parent / (a.output.stem + "_textures")
    tex_dir.mkdir(parents=True, exist_ok=True)
    for key, img in images.items():
        if key not in baked:
            continue
        img.filepath_raw = str(tex_dir / f"{key}.png")
        img.file_format = "PNG"
        img.save()

    links.new(tex["basecolor"].outputs["Color"], bsdf.inputs["Base Color"])
    if "roughness" in baked:
        links.new(tex["roughness"].outputs["Color"], bsdf.inputs["Roughness"])
    if "normal" in baked:
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -300)
        links.new(tex["normal"].outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Metallic"].default_value = 0.0

    mean_d, max_d = surface_distance(low, shell, height)
    bpy.data.objects.remove(shell, do_unlink=True)
    export_glb(a.output, [low])
    quads = sum(1 for p in low.data.polygons if len(p.vertices) == 4)
    stats = {
        "method": method,
        "high_triangles": high_tris,
        "voxel_size_m": round(voxel, 5),
        "voxel_faces": voxel_faces,
        "quadriflow_attempts": attempts,
        "low_faces": len(low.data.polygons),
        "low_quads_fraction": round(quads / max(1, len(low.data.polygons)), 3),
        "low_triangles": triangle_count(low),
        "texture_size": size,
        "baked": baked,
        "surface_error_mean": None if mean_d is None else round(mean_d, 5),
        "surface_error_max": None if max_d is None else round(max_d, 5),
        "seconds": round(time.monotonic() - t0, 1),
    }
    print("[retopo]", stats, flush=True)
    if a.stats:
        write_json(a.stats, stats)


if __name__ == "__main__":
    main()
