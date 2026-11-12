"""Assembly-only separation of a generated two-glove GLB into wrist pieces.

Hunyuan may reconstruct a pair of gloves as one horizontal object. We split
that mesh about its measured X midpoint and scale/place each side to an
approximate wrist anchor. Neither the original GLB nor its material files are
edited. This is a Blender-only approximation, NOT a rigging operation.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


def _bounds(objects):
    verts = [vert.co.copy() for obj in objects for vert in obj.data.vertices]
    if not verts:
        raise RuntimeError("No glove vertices after splitting")
    lower = Vector(tuple(min(v[i] for v in verts) for i in range(3)))
    upper = Vector(tuple(max(v[i] for v in verts) for i in range(3)))
    return lower, upper


def _half_mesh(source, x_mid: float, label: str):
    """Create one half of a textured mesh in world coordinates."""
    mesh = source.data.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.transform(source.matrix_world)
        bmesh.ops.bisect_plane(
            bm,
            geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
            dist=0.00001,
            plane_co=Vector((x_mid, 0, 0)),
            plane_no=Vector((1, 0, 0)),
            clear_inner=(label == "right"),
            clear_outer=(label == "left"),
        )
        if len(bm.faces) < 1:
            bpy.data.meshes.remove(mesh)
            return None
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    if not mesh.polygons:
        bpy.data.meshes.remove(mesh)
        return None
    return mesh


def _orient_and_place(mesh_objects, wrist, length, max_width, side):
    """Aim each approximately horizontal glove toward the floor."""
    lo, hi = _bounds(mesh_objects)
    extent = hi - lo
    major = max(range(3), key=lambda i: extent[i])
    if major == 0:
        angle = -math.pi / 2 if side == "left" else math.pi / 2
        rot = Matrix.Rotation(angle, 3, "Y")
    elif major == 1:
        rot = Matrix.Rotation(math.pi / 2, 3, "X")
    else:
        rot = Matrix.Identity(3)
    for obj in mesh_objects:
        for vert in obj.data.vertices:
            vert.co = rot @ vert.co
        obj.data.update()
    lo, hi = _bounds(mesh_objects)
    extent = hi - lo
    if extent.z <= 1e-6:
        raise RuntimeError("Degenerate glove length after orientation")
    breadth = max(extent.x, extent.y, 1e-6)
    scale = min(length / extent.z, max_width / breadth)
    if not 0.0001 < scale < 1000:
        raise RuntimeError(f"Implausible glove scale {scale}")
    mid_x = (lo.x + hi.x) * 0.5
    mid_y = (lo.y + hi.y) * 0.5
    target = Vector(wrist)
    for obj in mesh_objects:
        for vert in obj.data.vertices:
            p = vert.co
            vert.co = Vector((
                (p.x - mid_x) * scale + target.x,
                (p.y - mid_y) * scale + target.y,
                (p.z - hi.z) * scale + target.z,
            ))
        obj.data.update()
    return {"scale": round(scale, 6), "source_major_axis": "xyz"[major],
            "target_wrist": list(target)}


def split_glove_pair(part, layout):
    """Replace the imported glove pair with two independently selectable groups.

    This runs only on objects newly imported to the assembly working scene.
    All imported GLB source data on disk is left untouched.
    """
    if layout.get("mode") != "split_x_to_wrists_v1":
        raise RuntimeError("Unsupported glove pair layout")
    sources = list(part["meshes"])
    if not sources:
        raise RuntimeError("No imported glove meshes")
    collection = part["collection"]
    control = part["control"]
    x_mid = part["original_bounds_after_transform"]["center"][0]
    generated = []
    pieces = {}
    details = {}
    try:
        for label in ("left", "right"):
            pieces[label] = []
            for source in sources:
                mesh = _half_mesh(source, x_mid, label)
                if mesh is None:
                    continue
                obj = bpy.data.objects.new(f"AI3D_{label.upper()}_GLOVE_{source.name}", mesh)
                collection.objects.link(obj)
                generated.append(obj)
                pieces[label].append(obj)
            if not pieces[label]:
                raise RuntimeError(f"No {label} glove geometry on X split")
            details[label] = _orient_and_place(
                pieces[label],
                layout[f"{label}_wrist"],
                float(layout["hand_length"]),
                float(layout["hand_width"]),
                label,
            )
        # Validate both pieces BEFORE removing any imported assembly copy.
        if any(sum(len(o.data.polygons) for o in pieces[label]) < 4
               for label in ("left", "right")):
            raise RuntimeError("Glove split left too few faces on one side")
        bpy.context.view_layer.update()
        for label in ("left", "right"):
            anchor = bpy.data.objects.new(f"AI3D_{label.upper()}_WRIST_CONTROL", None)
            anchor.empty_display_type = "ARROWS"
            anchor.empty_display_size = float(layout["hand_length"]) * 0.2
            collection.objects.link(anchor)
            anchor.parent = control
            anchor.matrix_world = Matrix.Identity(4)
            generated.append(anchor)
            for obj in pieces[label]:
                obj.parent = anchor
                obj.matrix_world = Matrix.Identity(4)
        # The source pair is no longer needed in this working scene. Preserve
        # its materials/UVs in the two new Blender mesh copies. Save the
        # non-mesh references before invalidating their source Blender objects.
        original = [o for o in part["imported_objects"] if o not in sources]
        for source in sources:
            bpy.data.objects.remove(source, do_unlink=True)
    except Exception:
        for obj in generated:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        raise
    part["imported_objects"] = original + generated
    part["meshes"] = pieces["left"] + pieces["right"]
    part["mesh_count"] = len(part["meshes"])
    part["glove_split"] = {"status": "two_wrist_pieces",
                           "split_plane_x": x_mid, **details}
    bpy.context.view_layer.update()
    return part["glove_split"]
