"""Blender-only, reversible working-copy cutting and world-space guide planes.

The imported GLBs are treated as immutable inputs. For mode='apply' each
imported Blender mesh datablock is copied before a BMesh bisect; Blender only
writes the resulting scene into the separate assembly output directory.
No face filling, seam welding or automatic head replacement occurs here.
"""

import bmesh
import bpy
from mathutils import Vector


def _triangles(mesh):
    return sum(max(len(face.vertices) - 2, 0) for face in mesh.polygons)


def _boundaries(bm):
    return sum(1 for edge in bm.edges if len(edge.link_faces) == 1)


def guide_plane(collection, part_id, bounds, height):
    """A visible grid with *edges but no faces*, not part of the GLB export."""
    half_x = max(float(bounds["size"][0]) * 0.65, 0.15)
    half_y = max(float(bounds["size"][1]) * 0.80, 0.15)
    cx, cy = bounds["center"][:2]

    coordinates = []
    edges = []
    # Three evenly spaced lines per direction: enough to locate the plane
    # from side/front views without obscuring the model.
    for step in (-1.0, 0.0, 1.0):
        idx = len(coordinates)
        coordinates.extend([
            (cx - half_x, cy + step * half_y, height),
            (cx + half_x, cy + step * half_y, height),
        ])
        edges.append((idx, idx + 1))
        idx = len(coordinates)
        coordinates.extend([
            (cx + step * half_x, cy - half_y, height),
            (cx + step * half_x, cy + half_y, height),
        ])
        edges.append((idx, idx + 1))
    mesh = bpy.data.meshes.new(f"AI3D_{part_id}_CUT_GRID")
    mesh.from_pydata(coordinates, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(f"AI3D_{part_id}_CUT_GUIDE_Z", mesh)
    collection.objects.link(obj)
    obj.display_type = "WIRE"
    obj.show_in_front = True
    obj.hide_render = True
    obj.color = (1.0, 0.38, 0.15, 1.0)
    return obj


def bisect_part_world_z(part, plane_z, keep):
    """Trim a *copy* of each component mesh against the world-space Z plane.

    keep='below' keeps world Z <= plane_z (for the body).
    keep='above' keeps world Z >= plane_z (for the replacement head).
    Cutting produces open boundaries intentionally; the next milestone will
    handle fitting and welding.
    """
    bounds = part["original_bounds_after_transform"]
    lo, hi = bounds["min"][2], bounds["max"][2]
    if not lo < plane_z < hi:
        raise RuntimeError(
            f"Cut Z={plane_z} does not cross part {part['id']} "
            f"world bounds [{lo:.4f}, {hi:.4f}]"
        )

    before_triangles = sum(_triangles(obj.data) for obj in part["meshes"])
    before_boundaries = 0
    after_boundaries = 0
    for obj in part["meshes"]:
        # Never edit imported data in place: Blender meshes can be shared
        # among linked objects, and source GLBs are not writable from here.
        mesh = obj.data.copy()
        obj.data = mesh
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            before_boundaries += _boundaries(bm)
            normal = obj.matrix_world.to_3x3().transposed() @ Vector((0.0, 0.0, 1.0))
            normal.normalize()
            local_origin = obj.matrix_world.inverted() @ Vector((0.0, 0.0, plane_z))
            bmesh.ops.bisect_plane(
                bm,
                geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                dist=0.00001,
                plane_co=local_origin,
                plane_no=normal,
                clear_inner=(keep == "above"),
                clear_outer=(keep == "below"),
            )
            after_boundaries += _boundaries(bm)
            bm.to_mesh(mesh)
            mesh.update()
        finally:
            bm.free()

    bpy.context.view_layer.update()
    after_triangles = sum(_triangles(obj.data) for obj in part["meshes"])
    if after_triangles <= 0:
        raise RuntimeError(f"Cut eliminated all faces from {part['id']}; adjust Z")
    if after_triangles >= before_triangles:
        raise RuntimeError(
            f"Cut removed no faces from {part['id']}; adjust Z to intersect geometry"
        )
    return {
        "mode": "apply",
        "plane_z": plane_z,
        "keep": keep,
        "triangles_before": before_triangles,
        "triangles_after": after_triangles,
        "triangles_removed": before_triangles - after_triangles,
        "open_boundary_edges_before": before_boundaries,
        "open_boundary_edges_after": after_boundaries,
        "caps_added": False,
        "mesh_joined": False,
    }
