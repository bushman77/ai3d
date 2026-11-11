"""Blender background script: create a non-destructive two-part comparison scene.

Invoked via:
  blender --background --factory-startup --python-exit-code 1 \
    --python blender_assembly_preview.py -- --manifest <assembly.json>

Requires Blender's bundled bpy/mathutils; never edits the source GLBs.
"""

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def world_bounds(mesh_objects):
    points = [
        obj.matrix_world @ Vector(corner)
        for obj in mesh_objects for corner in obj.bound_box
    ]
    if not points:
        raise RuntimeError("Imported source contains no mesh bounding boxes")
    minimum = [min(float(p[i]) for p in points) for i in range(3)]
    maximum = [max(float(p[i]) for p in points) for i in range(3)]
    return {
        "min": minimum,
        "max": maximum,
        "center": [(lo + hi) / 2 for lo, hi in zip(minimum, maximum)],
        "size": [hi - lo for lo, hi in zip(minimum, maximum)],
    }


def create_part_collection(scene_root, index, identifier):
    collection = bpy.data.collections.new(f"{index:02d}_{identifier.upper()}")
    scene_root.children.link(collection)
    anchor = bpy.data.objects.new(f"AI3D_{identifier}_CONTROL", None)
    anchor.empty_display_type = "ARROWS"
    anchor.empty_display_size = 0.2
    collection.objects.link(anchor)
    return collection, anchor


def import_component(scene_root, part, index):
    source = Path(part["source"])
    if not source.is_file():
        raise RuntimeError(f"Source GLB not found for {part['id']}: {source}")

    collection, control = create_part_collection(scene_root, index, part["id"])
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(source))
    imported = set(bpy.context.scene.objects) - before
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"No mesh was imported from {source}")

    # Preserve every imported glTF node and its mesh/material relationships.
    # Only re-parent top-level import nodes to our separate control empty.
    for obj in imported:
        for old_collection in list(obj.users_collection):
            old_collection.objects.unlink(obj)
        collection.objects.link(obj)
    for obj in imported:
        if obj.parent not in imported:
            matrix_world = obj.matrix_world.copy()
            obj.parent = control
            obj.matrix_world = matrix_world

    transform = part["transform"]
    control.location = transform["position"]
    control.rotation_euler = [math.radians(x) for x in transform["rotation_deg"]]
    control.scale = transform["scale"]
    bpy.context.view_layer.update()
    bounds = world_bounds(meshes)
    return {
        "id": part["id"],
        "source": str(source),
        "control": control,
        "meshes": meshes,
        "imported_object_count": len(imported),
        "mesh_count": len(meshes),
        "triangles": sum(
            len(poly.vertices) - 2 for obj in meshes
            for poly in obj.data.polygons if len(poly.vertices) >= 3
        ),
        "original_bounds_after_transform": bounds,
    }


def view_setup(parts):
    meshes = [obj for part in parts for obj in part["meshes"]]
    bounds = world_bounds(meshes)
    center = Vector(bounds["center"])
    distance = max(max(bounds["size"]), 0.25) * 1.8
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.region_3d.view_location = center
            space.region_3d.view_distance = distance
            space.region_3d.view_perspective = "PERSP"
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            space.overlay.show_floor = True
    return bounds


def main():
    opts = arguments()
    manifest_path = opts.manifest.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 1 or len(manifest.get("parts", [])) != 2:
        raise RuntimeError("Expected a v1 two-part assembly manifest")
    if manifest.get("preview_layout") not in ("side_by_side", "overlay"):
        raise RuntimeError("Unknown preview_layout")

    # Factory-startup Blender scene has a cube, camera and light. Remove them,
    # but do not delete or touch source models on disk.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    scene_root = bpy.data.collections.new("AI3D_COMPONENTS")
    bpy.context.scene.collection.children.link(scene_root)
    results = [
        import_component(scene_root, part, i)
        for i, part in enumerate(manifest["parts"])
    ]

    stage_offsets = {part["id"]: [0.0, 0.0, 0.0] for part in manifest["parts"]}
    if manifest["preview_layout"] == "side_by_side":
        first = results[0]["original_bounds_after_transform"]
        second = results[1]["original_bounds_after_transform"]
        gap = max(first["size"][0] * 0.20, second["size"][0] * 0.20, 0.1)
        delta = first["max"][0] - second["min"][0] + gap
        results[1]["control"].location.x += delta
        stage_offsets[results[1]["id"]] = [float(delta), 0.0, 0.0]
        bpy.context.view_layer.update()

    for result in results:
        result["preview_bounds"] = world_bounds(result["meshes"])

    scene_bounds = view_setup(results)
    bpy.ops.object.select_all(action="DESELECT")
    results[0]["control"].select_set(True)
    bpy.context.view_layer.objects.active = results[0]["control"]

    report = {
        "manifest_version": 1,
        "character_id": manifest["character_id"],
        "preview_layout": manifest["preview_layout"],
        "blender_version": bpy.app.version_string,
        "scene_bounds": scene_bounds,
        "components": [{
            "id": item["id"],
            "source": item["source"],
            "control_object": item["control"].name,
            "imported_object_count": item["imported_object_count"],
            "mesh_count": item["mesh_count"],
            "triangles": item["triangles"],
            "bounds_with_user_transform": item["original_bounds_after_transform"],
            "staging_offset": stage_offsets[item["id"]],
            "preview_bounds": item["preview_bounds"],
        } for item in results],
        "warnings": [
            "Preview only: meshes remain separate, with no head-to-body fit.",
            "Side-by-side offsets are display-only and are not fitted attachment transforms.",
            "Original generated source GLBs are unchanged.",
            "No cutting, neck-bridging, merging, automatic rigging or production export.",
        ],
    }

    measurements = Path(manifest["output"]["measurements"])
    blend = Path(manifest["output"]["blend"])
    glb = Path(manifest["output"]["glb"])
    for target in (measurements, blend, glb):
        target.parent.mkdir(parents=True, exist_ok=True)

    measurements.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # A preview GLB has two independently selectable mesh groups and original
    # materials. It is NOT a fused or production-quality character.
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB",
        export_cameras=False, export_lights=False,
    )
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print(f"AI3D assembly preview saved: {blend}")
    print(f"AI3D standalone GLB comparison: {glb}")
    print(f"AI3D measurements saved: {measurements}")


if __name__ == "__main__":
    main()
