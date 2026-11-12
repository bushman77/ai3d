"""Blender-only, non-destructive upper-garment coverage pass.

Reduces doubled body faces *only* where the upper garment is close enough
to cover them. The original GLB and a hidden Blender backup remain intact.
This is an approximate spatial-coverage prototype, not UV retopology or
garment shrinkwrapping. Only the torso/upper-arm region is eligible.
"""
import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _world_bvh(mesh_objects):
    vertices = []
    triangles = []
    for obj in mesh_objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        offset = len(vertices)
        transform = obj.matrix_world
        vertices.extend(transform @ vertex.co for vertex in mesh.vertices)
        triangles.extend(
            tuple(offset + index for index in tri.vertices)
            for tri in mesh.loop_triangles
        )
    if not triangles:
        raise RuntimeError("Upper garment has no triangles for coverage checks")
    return BVHTree.FromPolygons(vertices, triangles, all_triangles=True)


def _backup_original_body(scene_root, meshes):
    backup = bpy.data.collections.new("AI3D_BODY_UNMASKED_BACKUP")
    scene_root.children.link(backup)
    for original in meshes:
        duplicate = original.copy()
        duplicate.data = original.data.copy()
        duplicate.name = "UNMASKED_" + original.name
        backup.objects.link(duplicate)
        duplicate.hide_set(True)
        duplicate.hide_render = True
        # Only meshes registered in the active component are exported;
        # these backups remain in the editable .blend for inspection.
    return backup


def replace_upper_body(scene_root, body, upper, config):
    """Suppress covered torso faces on imported body copies only.

    Candidate body faces must be in an anatomical height window AND have
    an outer garment surface nearby along the outward face normal. No
    garment = no removal. The pass deliberately avoids the head, lower
    body, feet and exposed hands. All deleted faces are reproducible from
    untouched imported sources whenever the assembly is rebuilt.
    """
    if config.get("mode") != "upper_coverage_v1":
        raise RuntimeError("Unsupported clothing replacement mode")
    bounds = body["original_bounds_after_transform"]
    minimum_z, maximum_z = bounds["min"][2], bounds["max"][2]
    height = maximum_z - minimum_z
    if height <= 1e-5:
        raise RuntimeError("Degenerate body height for upper coverage")
    lo = minimum_z + config["min_height_ratio"] * height
    hi = minimum_z + config["max_height_ratio"] * height
    garment_points = [
        obj.matrix_world @ Vector(corner)
        for obj in upper["meshes"] for corner in obj.bound_box
    ]
    garment_min_z = min(point.z for point in garment_points)
    garment_max_z = max(point.z for point in garment_points)
    lo = max(lo, garment_min_z)
    hi = min(hi, garment_max_z)
    distance = height * config["max_distance_ratio"]
    if lo >= hi:
        return {
            "mode": "upper_coverage_v1", "status": "no_vertical_overlap",
            "removed_faces": 0, "total_faces": sum(
                len(obj.data.polygons) for obj in body["meshes"]
            ), "backup_collection": None,
        }
    tree = _world_bvh(upper["meshes"])
    face_indices = {}
    total_faces = 0
    masked_faces = 0

    # Analyze all meshes before changing a single Blender working mesh.
    for obj in body["meshes"]:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            bm.faces.index_update()
            world = obj.matrix_world
            normal_matrix = world.to_3x3().inverted().transposed()
            mask = []
            total_faces += len(bm.faces)
            for face in bm.faces:
                p = world @ face.calc_center_median()
                if not (lo <= p.z <= hi):
                    continue
                normal = normal_matrix @ face.normal
                if normal.length < 1e-6:
                    continue
                normal.normalize()
                origin = p + normal * (height * 0.00005)
                ray = tree.ray_cast(origin, normal, distance)
                covered = ray[0] is not None and ray[3] is not None
                if not covered:
                    nearest = tree.find_nearest(p, distance)
                    if nearest[0] is not None and nearest[3] <= distance:
                        delta = nearest[0] - p
                        # A garment surface directly inward of the body is
                        # not coverage; keep this skin instead.
                        covered = delta.dot(normal) >= (height * -0.002)
                if covered:
                    mask.append(face.index)
            face_indices[obj] = mask
            masked_faces += len(mask)
        finally:
            bm.free()

    if total_faces == 0:
        raise RuntimeError("No body faces for upper coverage")
    ratio = masked_faces / total_faces
    if ratio > config["max_removed_fraction"]:
        raise RuntimeError(
            f"Upper garment mask would remove {ratio:.1%} of body faces; "
            "refusing unsafe over-cut"
        )
    report = {
        "mode": "upper_coverage_v1",
        "status": "applied" if masked_faces else "no_covered_faces",
        "removed_faces": masked_faces,
        "total_faces": total_faces,
        "removed_fraction": round(ratio, 5),
        "height_range_z": [round(lo, 6), round(hi, 6)],
        "max_distance": round(distance, 6),
        "backup_collection": None,
    }
    if masked_faces == 0:
        return report
    backup = _backup_original_body(scene_root, body["meshes"])
    report["backup_collection"] = backup.name
    for obj, indices in face_indices.items():
        if not indices:
            continue
        obj.data = obj.data.copy()
        mesh = obj.data
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            selected = [bm.faces[index] for index in indices]
            bmesh.ops.delete(bm, geom=selected, context="FACES")
            bm.to_mesh(mesh)
        finally:
            bm.free()
        mesh.update()
    bpy.context.view_layer.update()
    print(
        f"[UPPER COVERAGE] Removed {masked_faces}/{total_faces} body faces "
        f"beneath the upper outfit. Unmasked backup in {backup.name}.",
        flush=True,
    )
    return report
