"""Blender background script: create a non-destructive multi-part assembly scene.

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

# Blender is launched from the caller's current directory, which need not be
# the repository root. Add the source root before importing our Blender tools.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from ai3d.assembly.blender_cutting import guide_plane, bisect_part_world_z
from ai3d.characters.blender_glove_pair import split_glove_pair
from ai3d.characters.blender_clothing_replacement import replace_upper_body


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def world_bounds(mesh_objects):
    points = [
        obj.matrix_world @ Vector(corner)
        for obj in mesh_objects if len(obj.data.polygons) for corner in obj.bound_box
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
    if manifest.get("manifest_version") != 1 or len(manifest.get("parts", [])) < 2:
        raise RuntimeError("Expected a v1 assembly manifest with at least two parts")
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
    # Independent regions remain separate from the body, even if the base
    # already contains suit/hands/gear. Hair is included in the unified head.
    # Preserve old manifests that lacked visibility/export flags.
    for spec, result in zip(manifest["parts"], results):
        result["visible"] = spec.get("visible", True)
        result["include_in_preview"] = spec.get("include_in_preview", True)
        result["collection"] = result["control"].users_collection[0]
        result["imported_objects"] = list(result["collection"].objects)
        if not isinstance(result["visible"], bool) or not isinstance(result["include_in_preview"], bool):
            raise RuntimeError(f"Bad visibility/export flags for {result['id']}")

    stage_offsets = {part["id"]: [0.0, 0.0, 0.0] for part in manifest["parts"]}
    if manifest["preview_layout"] == "side_by_side":
        first = results[0]["original_bounds_after_transform"]
        second = results[1]["original_bounds_after_transform"]
        gap = max(first["size"][0] * 0.20, second["size"][0] * 0.20, 0.1)
        delta = first["max"][0] - second["min"][0] + gap
        results[1]["control"].location.x += delta
        stage_offsets[results[1]["id"]] = [float(delta), 0.0, 0.0]
        bpy.context.view_layer.update()

    # Three cut states: 'off' changes nothing; 'guide' draws an editable
    # plane visualization; 'apply' bisects only Blender's imported mesh copies.
    # Each stage can be reversed by changing the manifest to 'off' and rebuild.
    guides = bpy.data.collections.new("AI3D_CUT_GUIDES")
    scene_root.children.link(guides)
    cut_results = {}
    for spec, result in zip(manifest["parts"], results):
        cut = spec.get("cut") or {"mode": "off"}
        mode = cut.get("mode", "off")
        if mode not in ("off", "guide", "apply"):
            raise RuntimeError(f"Invalid cut mode on {result['id']}: {mode}")
        report = {"mode": mode}
        if mode != "off":
            height = float(cut["plane_z"])
            if cut.get("show_guide", True):
                guide_plane(
                    guides, result["id"],
                    result["original_bounds_after_transform"], height
                )
            report.update({"plane_z": height, "keep": cut["keep"]})
            if mode == "apply":
                report.update(bisect_part_world_z(result, height, cut["keep"]))
        cut_results[result["id"]] = report

    # Gloves can arrive from Hunyuan as a single horizontally arranged pair.
    # A manifest fit plan separates the two working halves and anchors them
    # to estimated wrist locations; source GLBs are never modified.
    for spec, result in zip(manifest["parts"], results):
        layout = spec.get("pair_layout")
        if layout is not None:
            if spec["id"] != "hands":
                raise RuntimeError("Pair split is only supported for hands")
            result["glove_split"] = split_glove_pair(result, layout)

    # Opt-in coverage pass hides only imported body faces under the upper
    # garment. The original GLB is unchanged, and a hidden original-body copy
    # is preserved in the .blend before any removal happens.
    clothing_report = {"mode": "off", "status": "disabled", "removed_faces": 0}
    clothing_plan = manifest.get("clothing_replacement", {"mode": "off"})
    if clothing_plan.get("mode") == "upper_coverage_v1":
        part_lookup = {item["id"]: item for item in results}
        if not {"body", "upper_outfit"} <= part_lookup.keys():
            raise RuntimeError("Upper clothing coverage requires body and upper_outfit")
        if manifest["preview_layout"] != "overlay":
            raise RuntimeError("Upper clothing coverage requires overlay layout")
        clothing_report = replace_upper_body(
            scene_root, part_lookup["body"], part_lookup["upper_outfit"],
            clothing_plan,
        )

    for result in results:
        result["preview_bounds"] = world_bounds(result["meshes"])

    # Stage hidden parts *after* bounds and bisect calculations; they remain
    # available as named, individually selectable Blender collections.
    for result in results:
        if not result["visible"]:
            for obj in result["imported_objects"]:
                obj.hide_set(True)
                obj.hide_render = True
    visible_parts = [r for r in results if r["visible"]]
    if not visible_parts:
        raise RuntimeError("No visible component to frame in Blender")
    scene_bounds = view_setup(visible_parts)
    bpy.ops.object.select_all(action="DESELECT")
    results[0]["control"].select_set(True)
    bpy.context.view_layer.objects.active = results[0]["control"]

    report = {
        "manifest_version": 1,
        "character_id": manifest["character_id"],
        "preview_layout": manifest["preview_layout"],
        "blender_version": bpy.app.version_string,
        "clothing_replacement": clothing_report,
        "scene_bounds": scene_bounds,
        "components": [{
            "id": item["id"],
            "source": item["source"],
            "control_object": item["control"].name,
            "imported_object_count": item["imported_object_count"],
            "mesh_count": item["mesh_count"],
            "triangles": item["triangles"],  # Retain legacy report field.
            "visible": item["visible"],
            "include_in_preview": item["include_in_preview"],
            "status": manifest["parts"][i].get("status", "unfitted"),
            "triangles_before": item["triangles"],
            "triangles_after": sum(
                len(poly.vertices) - 2 for obj in item["meshes"]
                for poly in obj.data.polygons if len(poly.vertices) >= 3
            ),
            "cut": cut_results[item["id"]],
            "bounds_with_user_transform": item["original_bounds_after_transform"],
            "staging_offset": stage_offsets[item["id"]],
            "preview_bounds": item["preview_bounds"],
            "glove_split": item.get("glove_split"),
        } for i, item in enumerate(results)],
        "warnings": [
            "Preview only: independent meshes remain separate and unfused.",
            "Clothing uses approximate anatomical boxes; gloves split into two wrist pieces.",
            "Side-by-side offsets are display-only and are not fitted attachment transforms.",
            "Original generated source GLBs are unchanged.",
            "Cutting is optional and applies only to imported working meshes.",
            "Cut planes do NOT cap holes, stitch neck seams, replace parts, or rig the character.",
            "Optional upper coverage removes only body faces beneath detected garment surfaces.",
            "This is not a production character export.",
        ],
    }

    measurements = Path(manifest["output"]["measurements"])
    blend = Path(manifest["output"]["blend"])
    glb = Path(manifest["output"]["glb"])
    for target in (measurements, blend, glb):
        target.parent.mkdir(parents=True, exist_ok=True)

    measurements.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # The GLB contains only explicitly enabled components; staged parts
    # remain available in preview.blend but cannot silently duplicate the
    # body on export. All exported meshes remain separate objects.
    included = [r for r in results if r["include_in_preview"]]
    if not included:
        raise RuntimeError("No components enabled for comparison GLB export")
    # The cut grid is an editor-only visual. Temporarily remove its collection
    # before exporting the comparison GLB, then restore it for the .blend file.
    scene_root.children.unlink(guides)
    # Explicit exporter selection is safer than relying on hide_viewport and
    # hide_render behavior, which varies across Blender/glTF versions.
    for part in results:
        for obj in part["imported_objects"]:
            if part["include_in_preview"]:
                obj.hide_set(False)
            obj.select_set(part["include_in_preview"])
    try:
        bpy.ops.export_scene.gltf(
            filepath=str(glb), export_format="GLB",
            use_selection=True, export_cameras=False, export_lights=False,
        )
    finally:
        scene_root.children.link(guides)
        for part in results:
            if not part["visible"]:
                for obj in part["imported_objects"]:
                    obj.hide_set(True)
        bpy.ops.object.select_all(action="DESELECT")
        results[0]["control"].select_set(True)
        bpy.context.view_layer.objects.active = results[0]["control"]
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print(f"AI3D assembly preview saved: {blend}")
    print(f"AI3D standalone GLB comparison: {glb}")
    print(f"AI3D measurements saved: {measurements}")


if __name__ == "__main__":
    main()
