"""Blender-only non-destructive, diagnostic thigh-underlay scene builder.

Usage:
 blender --background path/to/hole_in_thigh_exposed.blend \\
   --python-exit-code 1 --python ai3d/diagnostics/blender_thigh_prototype.py \\
   -- --output path/to/thigh_underlay_prototype.blend

Creates a new .blend. NEVER saves over the source scene. This is only a
visible fitting prototype; it has no rig/UV/cloth texture and does not repair
or delete the old holster geometry. Inspect in Blender before using anything
in a game export.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ai3d.diagnostics.thigh_underlay import build_mara_underlay
from ai3d.diagnostics.guided_thigh_patch import build_mesh_guided_thigh_patch
from ai3d.diagnostics.blender_review_helper import add_non_destructive_remnant_review


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object", default="Mesh")
    parser.add_argument("--inset", type=float, default=0.0)
    parser.add_argument("--method", choices=("guided", "stations"), default="guided")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--review-remnants", action="store_true",
                        help="Create a separate preview body with 3 verified candidates isolated")
    args = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    return parser.parse_args(args)


def main():
    args = parse_args()
    source = Path(bpy.data.filepath).expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".blend":
        raise RuntimeError("Load an existing .blend as Blender's first argument")
    if output == source:
        raise RuntimeError("Refusing to overwrite the input scene")
    if output.suffix.lower() != ".blend":
        raise RuntimeError("Prototype output must end in .blend")
    if args.output.is_symlink():
        raise RuntimeError("Refusing symlink destination")
    if output.exists() and not args.overwrite:
        raise RuntimeError("Prototype already exists; pass --force to rebuild separately")
    if args.review_remnants and args.method != "guided":
        raise RuntimeError("Remnant review is supported only with the guided panel")
    body = bpy.data.objects.get(args.object)
    if body is None or body.type != "MESH":
        raise RuntimeError(f"Cannot find body mesh object {args.object!r}")
    # This prototype was measured against one exact Mara experimental source.
    # Reject other characters rather than applying its empirical stations.
    if body.mode == "EDIT":
        if bpy.context.active_object != body:
            raise RuntimeError("Please save the diagnostic scene with its body as the active mesh")
        bpy.ops.object.mode_set(mode="OBJECT")
    if len(body.data.vertices) != 20633 or len(body.data.polygons) != 33129:
        raise RuntimeError("Mesh differs from the measured Mara experimental source; do not auto-fit")
    if any(abs(body.matrix_world[i][j] - (1.0 if i == j else 0.0)) > 1e-5
           for i in range(4) for j in range(4)):
        raise RuntimeError("Body world transform differs from measured identity transform")

    if args.method == "guided":
        # Original body polygons, not the detached holster meshes. The
        # geometry function identifies substantial leg-spanning islands.
        points = [tuple(body.matrix_world @ vert.co) for vert in body.data.vertices]
        source_faces = [tuple(poly.vertices) for poly in body.data.polygons]
        vertices, faces, diagnostics = build_mesh_guided_thigh_patch(
            points, source_faces, inset=args.inset,
            edge_embed=0.004 if args.review_remnants else 0.0,
        )
        object_name = "AI3D_Thigh_GuidedPatch_TEST"
        mesh_name = "AI3D_thigh_guided_patch_test_mesh"
    else:
        vertices, faces = build_mara_underlay(inset=args.inset)
        diagnostics = {"method": "fixed_station_closed_underlay"}
        object_name = "AI3D_Thigh_Underlay_TEST"
        mesh_name = "AI3D_thigh_underlay_test_mesh"
    if bpy.data.objects.get(object_name):
        raise RuntimeError(f"This scene already contains {object_name}")
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    patch = bpy.data.objects.new(object_name, mesh)
    group = bpy.data.collections.new("AI3D_THIGH_REPAIR_PROTOTYPE")
    bpy.context.scene.collection.children.link(group)
    group.objects.link(patch)

    material = bpy.data.materials.new("AI3D_DIAGNOSTIC_CYAN_NOT_FINAL")
    material.diffuse_color = (0.02, 0.72, 0.95, 1.0)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = (0.02, 0.72, 0.95, 1.0)
        principled.inputs["Roughness"].default_value = 0.65
    mesh.materials.append(material)

    patch["prototype_only"] = True
    patch["source_scene"] = str(source)
    patch["fit_reason"] = "experimental negative-X thigh underlay; no mesh weld"
    patch["fitting_method"] = args.method
    patch["fitting_metadata_json"] = json.dumps(diagnostics, sort_keys=True)
    patch["inset"] = args.inset
    if args.review_remnants:
        selection = add_non_destructive_remnant_review(body)
        patch["remnant_review"] = ", ".join(selection.names)
        patch["remnant_review_faces"] = len(selection.face_indices)

    # New file only. Existing body, head, clothing, selections, sources and
    # other assets are retained in-memory for this separate inspectable scene.
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    if not output.is_file():
        raise RuntimeError("Blender did not write a prototype scene")
    print("\nAI3D MARA THIGH UNDERLAY PROTOTYPE", flush=True)
    print(f"  Original (unchanged): {source}", flush=True)
    print(f"  Preview scene: {output}", flush=True)
    print(f"  Object: {patch.name} (method={args.method})", flush=True)
    if args.method == "guided":
        print(f"  Support islands: {diagnostics['source_islands']}", flush=True)
        print(f"  Supported rings front/rear: {diagnostics['front_supported_rings']}/{diagnostics['rear_supported_rings']}", flush=True)
    print(f"  Prototype vertices: {len(vertices)}; faces: {len(faces)}", flush=True)
    if args.review_remnants:
        print(f"  Remnants hidden ONLY in body preview copy: {', '.join(selection.names)}", flush=True)
        print(f"  Faces isolated for review: {len(selection.face_indices)}", flush=True)
        print("  Inspect AI3D_HOLSTER_REMNANT_REVIEW to toggle source/candidate meshes.", flush=True)
    print("  NOT approved for gameplay. Mesh-guided patch is OPEN, not joined or textured.", flush=True)
    print("  Check front, side and 3/4 views, old holster fragments and edge gaps.", flush=True)


if __name__ == "__main__":
    main()
