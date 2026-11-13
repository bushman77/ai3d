"""Blender background pass: add editable *unskinned* bones to a saved assembly.

Invoked by ai3d.rigging.prototype. Only writes a separate .blend and JSON
report; source .blend, component GLBs and assembly manifests are untouched.
Run through Blender's Python interpreter, not the AI3D Python venv.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai3d.rigging.landmarks import humanoid_bones


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(args)


def bounds(meshes, label):
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes if obj.type == "MESH" and len(obj.data.polygons) > 0
        for corner in obj.bound_box
    ]
    if not corners:
        raise RuntimeError(f"No visible geometry for {label} in the assembled scene")
    return {
        "min": [min(float(p[i]) for p in corners) for i in range(3)],
        "max": [max(float(p[i]) for p in corners) for i in range(3)],
    }


def component_meshes(identifier):
    control_name = f"AI3D_{identifier}_CONTROL"
    control = bpy.data.objects.get(control_name)
    if control is None:
        if identifier == "head":
            return []
        raise RuntimeError(f"Missing {control_name}; expected an AI3D assembly preview")
    # Imported GLB hierarchy has independent child empties/meshes.
    # Use the component's own descendant meshes, not clothing or backup meshes.
    descendants = list(control.children_recursive)
    return [
        obj for obj in descendants
        if obj.type == "MESH" and not obj.hide_render and
        not obj.hide_get() and len(obj.data.polygons) > 0
    ]


def create_armature(plan):
    arm_data = bpy.data.armatures.new("AI3D_Humanoid_Prototype")
    arm_obj = bpy.data.objects.new("AI3D_Humanoid_Prototype", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    arm_obj.show_in_front = True
    arm_data.display_type = "STICK"
    arm_data.show_names = True

    bpy.ops.object.select_all(action="DESELECT")
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for spec in plan["bones"]:
            joint = arm_data.edit_bones.new(spec["name"])
            joint.head = spec["head"]
            joint.tail = spec["tail"]
        for spec in plan["bones"]:
            if spec["parent"]:
                arm_data.edit_bones[spec["name"]].parent = arm_data.edit_bones[spec["parent"]]
        # Keep all initial joints independent; users can correct bone locations
        # without Blender snapping connected endpoints to other estimates.
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def open_viewport(arm):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if hasattr(space.overlay, "show_bones"):
                space.overlay.show_bones = True
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            space.region_3d.view_perspective = "PERSP"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm


def main():
    args = arguments()
    source = args.source.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    report_path = args.report.expanduser().resolve()
    if source.suffix.lower() != ".blend" or source == output:
        raise RuntimeError("Rig source must be a distinct, existing .blend file")
    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError("Assembly Blender file is empty")

    bpy.ops.wm.open_mainfile(filepath=str(source))
    bpy.context.view_layer.update()
    body = bounds(component_meshes("body"), "body")
    heads = component_meshes("head")
    head = bounds(heads, "head") if heads else None
    plan = humanoid_bones(body, head)
    if bpy.data.objects.get("AI3D_Humanoid_Prototype"):
        raise RuntimeError("Source already contains a prototype armature; choose a clean assembly")

    arm = create_armature(plan)
    open_viewport(arm)
    plan["source_scene"] = str(source)
    plan["armature"] = arm.name
    plan["skinned"] = False
    plan["animated"] = False
    plan["mesh_modified"] = False
    plan["blender_version"] = bpy.app.version_string
    plan["component_objects"] = sorted(
        obj.name for obj in bpy.context.scene.objects if obj.type == "MESH"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # A copied, editable Blender scene is the sole preview output. An armature
    # without vertex weights is NOT a skinned character or an animated GLB.
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"AI3D skeleton prototype: {len(plan['bones'])} bones", flush=True)
    print("AI3D rig scene:", output, flush=True)
    print("AI3D estimated joints:", report_path, flush=True)


if __name__ == "__main__":
    main()
