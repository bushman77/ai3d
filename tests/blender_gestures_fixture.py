"""Round-trips a synthetic Mixamo-style FBX through rig.add_gesture_actions.

Run inside Blender:
  blender --background --python tests/blender_gestures_fixture.py -- --out REPORT.json

Builds a source skeleton in a T-pose rest with Mixamo names and one finger
bone, animates an arm by a known rotation, exports FBX, then merges it onto a
target skeleton whose rest is an A-pose and which has no fingers. Writes what
the merge produced so the test can assert on it outside Blender.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai3d" / "blender"))

import bpy  # noqa: E402
from mathutils import Quaternion, Vector  # noqa: E402

import rig as R  # noqa: E402
from common import reset_scene, select_only  # noqa: E402

CLIP = "brush_shoulder"
TURN_DEGREES = 40.0

# Same joints, different rest: the source stands in a T, the target in an A,
# and only the source has a finger. A raw copy of local rotations would be
# wrong between the two; a retarget must not be.
SOURCE = [("mixamorig:Hips", (0, 0, 1), (0, 0, 1.2), None),
          ("mixamorig:Spine", (0, 0, 1.2), (0, 0, 1.5), "mixamorig:Hips"),
          ("mixamorig:LeftArm", (0.2, 0, 1.5), (0.7, 0, 1.5), "mixamorig:Spine"),
          ("mixamorig:LeftForeArm", (0.7, 0, 1.5), (1.1, 0, 1.5), "mixamorig:LeftArm"),
          ("mixamorig:LeftHand", (1.1, 0, 1.5), (1.25, 0, 1.5), "mixamorig:LeftForeArm"),
          ("mixamorig:LeftHandIndex1", (1.25, 0, 1.5), (1.35, 0, 1.5), "mixamorig:LeftHand")]
TARGET = [("mixamorig:Hips", (0, 0, 1), (0, 0, 1.2), None),
          ("mixamorig:Spine", (0, 0, 1.2), (0, 0, 1.5), "mixamorig:Hips"),
          ("mixamorig:LeftArm", (0.2, 0, 1.5), (0.55, 0, 1.15), "mixamorig:Spine"),
          ("mixamorig:LeftForeArm", (0.55, 0, 1.15), (0.83, 0, 0.87), "mixamorig:LeftArm"),
          ("mixamorig:LeftHand", (0.83, 0, 0.87), (0.93, 0, 0.77), "mixamorig:LeftForeArm")]


def build(name, bones):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, head, tail, parent in bones:
        edit = data.edit_bones.new(bone_name)
        edit.head, edit.tail = Vector(head), Vector(tail)
        if parent:
            edit.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return obj


def action_fcurves(action):
    """Blender 4.4+ moved F-curves into layers/slots; 5.x dropped
    action.fcurves. Read both shapes."""
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    found = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                found.extend(bag.fcurves)
    return found


def world_delta(pose_bone):
    rest = pose_bone.bone.matrix_local.to_3x3()
    return (pose_bone.matrix.to_3x3() @ rest.inverted()).to_quaternion()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

    folder = Path(tempfile.mkdtemp())
    turn = Quaternion(Vector((0, 0, 1)), math.radians(TURN_DEGREES))

    reset_scene()
    source = build("SOURCE", SOURCE)
    select_only([source])
    bpy.ops.object.mode_set(mode="POSE")
    action = bpy.data.actions.new(CLIP)
    action.use_fake_user = True
    source.animation_data_create()
    source.animation_data.action = action
    bone = source.pose.bones["mixamorig:LeftArm"]
    bone.rotation_mode = "QUATERNION"
    for frame, value in ((1, Quaternion()), (10, R.quat_world_to_local(bone, turn))):
        bone.rotation_quaternion = value
        bone.keyframe_insert("rotation_quaternion", frame=frame)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.export_scene.fbx(filepath=str(folder / f"{CLIP}.fbx"),
                             use_selection=False, add_leaf_bones=False)

    reset_scene()
    target = build("TARGET", TARGET)
    made = R.add_gesture_actions(target, folder)

    report = {"made": made, "bones": [], "rotation_only": True,
              "turn_degrees": TURN_DEGREES}
    if made:
        merged = bpy.data.actions[made[0]]
        paths = [fc.data_path for fc in action_fcurves(merged)]
        report["bones"] = sorted({p.split('"')[1] for p in paths})
        report["curves"] = len(paths)
        report["rotation_only"] = all(p.endswith(".rotation_quaternion") for p in paths)
        target.animation_data_create()
        target.animation_data.action = merged
        bpy.context.scene.frame_set(int(round(merged.frame_range[1])))
        posed = world_delta(target.pose.bones["mixamorig:LeftArm"])
        report["reached_degrees"] = math.degrees(posed.angle)
        report["axis_error_degrees"] = math.degrees(posed.rotation_difference(turn).angle)
        bpy.context.scene.frame_set(1)
        report["rest_degrees"] = math.degrees(
            world_delta(target.pose.bones["mixamorig:LeftArm"]).angle)
    args.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
