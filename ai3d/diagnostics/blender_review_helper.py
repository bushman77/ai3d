"""Blender adapter: reversibly isolate verified holster candidates in copies.

Only duplicated meshes are edited, and only in a distinct preview .blend.
The unchanged body and the candidate-only copy remain accessible in Outliner.
"""

from __future__ import annotations

import bmesh
import bpy
from ai3d.diagnostics.holster_review import identify_remnant_islands


def _subset_faces_on_copy(obj, kept_indices):
    mesh = obj.data
    count_before = len(mesh.polygons)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        if len(bm.faces) != count_before:
            raise RuntimeError("Mesh face indices changed before preview isolation")
        to_delete = [bm.faces[i] for i in range(count_before) if i not in kept_indices]
        bmesh.ops.delete(bm, geom=to_delete, context="FACES")
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    if len(mesh.polygons) != len(kept_indices):
        raise RuntimeError("Preview face isolation produced an unexpected face count")


def add_non_destructive_remnant_review(body):
    if body.type != "MESH" or body.mode != "OBJECT":
        raise RuntimeError("The experimental Mara body must be in Object Mode")

    points = [tuple(float(v) for v in body.matrix_world @ vert.co)
              for vert in body.data.vertices]
    faces = [tuple(int(i) for i in poly.vertices) for poly in body.data.polygons]
    selection = identify_remnant_islands(points, faces)
    removal = set(selection.face_indices)
    all_faces = set(range(len(faces)))
    if len(removal) != 147 or len(all_faces-removal) != len(faces)-147:
        raise RuntimeError("Unexpected remnant selection; no preview changes made")

    if bpy.data.objects.get("AI3D_Mara_Body_RemnantsHidden_TEST"):
        raise RuntimeError("Preview already contains a no-remnants body")
    if bpy.data.objects.get("AI3D_Holster_Candidates_REVIEW"):
        raise RuntimeError("Preview already contains remnant candidates")

    collection = bpy.data.collections.new("AI3D_HOLSTER_REMNANT_REVIEW")
    bpy.context.scene.collection.children.link(collection)

    cleaned = body.copy()
    cleaned.name = "AI3D_Mara_Body_RemnantsHidden_TEST"
    cleaned.data = body.data.copy()  # Preserves material slots, UVs, colors
    collection.objects.link(cleaned)

    isolated = body.copy()
    isolated.name = "AI3D_Holster_Candidates_REVIEW"
    isolated.data = body.data.copy()
    collection.objects.link(isolated)

    _subset_faces_on_copy(cleaned, all_faces-removal)
    _subset_faces_on_copy(isolated, removal)

    cleaned["preview_only"] = True
    cleaned["selected_islands"] = ", ".join(selection.names)
    cleaned["faces_hidden_in_copy"] = len(removal)
    isolated["review_only"] = True
    isolated["candidate_names"] = ", ".join(selection.names)
    isolated["faces"] = len(removal)

    # All changes are in the new preview scene. Source .blend is never saved.
    body.hide_set(True)
    body.hide_render = True
    cleaned.hide_set(False)
    cleaned.hide_render = False
    isolated.hide_set(True)
    isolated.hide_render = True
    bpy.ops.object.select_all(action="DESELECT")
    cleaned.select_set(True)
    bpy.context.view_layer.objects.active = cleaned
    if len(body.data.polygons) != len(faces):
        raise RuntimeError("The original body was unexpectedly modified")
    return selection
