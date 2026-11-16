"""Acceptance validation for generated Space Nova Blender and GLB rigs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
sys.dont_write_bytecode = True

from generator import HumanoidProportions, NEUTRAL_FRAME, POSE_FRAMES, TEMPLATES


POSE_PROBES = {
    "shoulder_rotation": "upper_arm.L",
    "elbow_bending": "forearm.L",
    "knee_bending": "shin.L",
    "hip_movement": "pelvis",
    "head_turning": "head",
}
MINIMUM_POSE_DISPLACEMENT_METRES = 0.005
POSITION_TOLERANCE = 1.0e-5
WEIGHT_TOLERANCE = 1.0e-5


class ValidationFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationFailure(message)


def blender_arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_arguments() -> argparse.Namespace:
    default_output = SCRIPT_DIRECTORY / "output"
    parser = argparse.ArgumentParser(description="Validate Space Nova rig templates")
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--report", type=Path, help="validation JSON path")
    return parser.parse_args(blender_arguments())


def armature_signature(armature: bpy.types.Object) -> tuple[tuple[str, str | None], ...]:
    return tuple(
        sorted((bone.name, bone.parent.name if bone.parent else None) for bone in armature.data.bones)
    )


def mirror(vector: Vector) -> Vector:
    return Vector((-vector.x, vector.y, vector.z))


def validate_symmetry(armature: bpy.types.Object) -> int:
    bones = armature.data.bones
    checked = 0
    for left in (bone for bone in bones if bone.name.endswith(".L")):
        right_name = f"{left.name[:-2]}.R"
        right = bones.get(right_name)
        require(right is not None, f"missing mirrored bone {right_name}")
        require((mirror(left.head_local) - right.head_local).length <= POSITION_TOLERANCE, f"asymmetric head: {left.name}")
        require((mirror(left.tail_local) - right.tail_local).length <= POSITION_TOLERANCE, f"asymmetric tail: {left.name}")
        require(abs(left.length - right.length) <= POSITION_TOLERANCE, f"asymmetric length: {left.name}")

        left_parent = left.parent.name if left.parent else None
        expected_parent = left_parent[:-2] + ".R" if left_parent and left_parent.endswith(".L") else left_parent
        actual_parent = right.parent.name if right.parent else None
        require(actual_parent == expected_parent, f"asymmetric parent: {right_name}")
        checked += 1

    require(checked > 0, "no left/right bones were checked")
    require(sum(1 for bone in bones if bone.name.endswith(".R")) == checked, "unpaired right-side bones")
    return checked


def mesh_armature_modifier(mesh: bpy.types.Object) -> bpy.types.ArmatureModifier:
    modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
    require(len(modifiers) == 1, f"{mesh.name} must have exactly one armature modifier")
    return modifiers[0]


def validate_weights(
    mesh: bpy.types.Object,
    armature: bpy.types.Object,
    *,
    expected_weighted_bones: set[str] | None = None,
) -> dict[str, Any]:
    modifier = mesh_armature_modifier(mesh)
    require(modifier.object == armature, f"{mesh.name} armature modifier targets the wrong rig")

    bone_names = {bone.name for bone in armature.data.bones}
    deform_names = {bone.name for bone in armature.data.bones if bone.use_deform}
    group_names = {group.name for group in mesh.vertex_groups}
    expected_groups = expected_weighted_bones if expected_weighted_bones is not None else deform_names
    if expected_weighted_bones is None:
        require(group_names == expected_groups, "vertex groups do not match the deform bones")
    else:
        require(expected_groups <= group_names, "GLB reimport dropped one or more weighted groups")
        require(group_names <= bone_names, "GLB reimport created a non-bone vertex group")

    weighted_groups: set[str] = set()
    for vertex in mesh.data.vertices:
        require(vertex.groups, f"vertex {vertex.index} has no skin weights")
        weight_sum = 0.0
        for membership in vertex.groups:
            group_name = mesh.vertex_groups[membership.group].name
            require(group_name in bone_names, f"vertex {vertex.index} references non-bone group {group_name}")
            require(math.isfinite(membership.weight) and membership.weight > 0.0, f"invalid weight on vertex {vertex.index}")
            weight_sum += membership.weight
            weighted_groups.add(group_name)
        require(abs(weight_sum - 1.0) <= WEIGHT_TOLERANCE, f"weights on vertex {vertex.index} sum to {weight_sum}")

    require(weighted_groups == expected_groups, "one or more expected bones have no weighted vertices")
    return {
        "vertices": len(mesh.data.vertices),
        "faces": len(mesh.data.polygons),
        "weighted_bones": len(weighted_groups),
        "weights_normalized": True,
    }


def group_vertex_indices(mesh: bpy.types.Object, group_name: str) -> list[int]:
    group = mesh.vertex_groups.get(group_name)
    require(group is not None, f"missing pose probe group {group_name}")
    return [
        vertex.index
        for vertex in mesh.data.vertices
        if any(membership.group == group.index and membership.weight > 0.0 for membership in vertex.groups)
    ]


def evaluated_positions(mesh: bpy.types.Object) -> list[Vector]:
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    dependency_graph.update()
    evaluated_object = mesh.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        matrix = evaluated_object.matrix_world
        positions = [matrix @ vertex.co for vertex in evaluated_mesh.vertices]
    finally:
        evaluated_object.to_mesh_clear()
    return positions


def validate_pose_tests(mesh: bpy.types.Object, armature: bpy.types.Object) -> dict[str, float]:
    require(armature.animation_data is not None, "rig has no animation data")
    require(armature.animation_data.action is not None, "rig has no active pose-test action")
    require(armature.animation_data.action.name == "SpaceNovaPoseTests", "unexpected pose-test action name")

    bpy.context.scene.frame_set(NEUTRAL_FRAME)
    neutral = evaluated_positions(mesh)
    displacements: dict[str, float] = {}

    for test_name, frame in POSE_FRAMES.items():
        probe_name = POSE_PROBES[test_name]
        indices = group_vertex_indices(mesh, probe_name)
        require(indices, f"pose probe {probe_name} has no vertices")
        bpy.context.scene.frame_set(frame)
        posed = evaluated_positions(mesh)
        require(len(posed) == len(neutral), f"pose {test_name} changed vertex count")
        require(all(all(math.isfinite(value) for value in point) for point in posed), f"pose {test_name} produced non-finite vertices")
        displacement = max((posed[index] - neutral[index]).length for index in indices)
        require(displacement >= MINIMUM_POSE_DISPLACEMENT_METRES, f"pose {test_name} did not deform its probe region")
        displacements[test_name] = round(displacement, 6)

    bpy.context.scene.frame_set(NEUTRAL_FRAME)
    return displacements


def validate_configuration_controls() -> list[str]:
    expected = {
        "shoulder_width",
        "pelvis_width",
        "torso_length",
        "arm_length",
        "leg_length",
        "neck_length",
        "head_width",
        "head_depth",
        "head_height",
    }
    actual = {item.name for item in fields(HumanoidProportions)}
    require(actual == expected, "anatomical configuration controls changed unexpectedly")

    defaults = TEMPLATES["female"].proportions
    for control in expected:
        changed_value = getattr(defaults, control) * 1.02
        changed = defaults.with_overrides({control: changed_value})
        require(getattr(changed, control) == changed_value, f"configuration control {control} was ignored")
        for unchanged in expected - {control}:
            require(
                getattr(changed, unchanged) == getattr(defaults, unchanged),
                f"configuration control {control} unexpectedly changed {unchanged}",
            )
    return sorted(expected)


def validate_glb_reimport(glb_path: Path, expected_signature: tuple[tuple[str, str | None], ...]) -> dict[str, Any]:
    require(glb_path.is_file(), f"missing GLB: {glb_path}")
    require(glb_path.stat().st_size > 1000, f"GLB is unexpectedly small: {glb_path}")
    with glb_path.open("rb") as handle:
        require(handle.read(4) == b"glTF", f"invalid GLB header: {glb_path}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    # User startup handlers and enabled add-ons may create helper objects even
    # when ``use_empty`` is requested.  Remove them explicitly so this is a
    # genuine clean-scene import rather than making the validator dependent on
    # a workstation's Blender preferences.
    for existing_object in list(bpy.data.objects):
        bpy.data.objects.remove(existing_object, do_unlink=True)
    result = bpy.ops.import_scene.gltf(filepath=str(glb_path))
    require("FINISHED" in result, f"GLB import operator failed: {glb_path}")

    armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    require(len(armatures) == 1, f"GLB reimport expected one armature, found {len(armatures)}")
    meshes = [
        item
        for item in bpy.context.scene.objects
        if item.type == "MESH"
        and any(
            modifier.type == "ARMATURE" and modifier.object == armatures[0]
            for modifier in item.modifiers
        )
    ]
    require(len(meshes) == 1, f"GLB reimport expected one skinned mesh, found {len(meshes)}")
    require(armature_signature(armatures[0]) == expected_signature, "GLB reimport changed bone names or hierarchy")
    # glTF has no Blender-specific ``Bone.use_deform`` flag.  Blender's
    # importer consequently marks root as deforming even though the exported
    # skin correctly has no root vertex group.  Validate against the canonical
    # weighted set rather than that non-portable UI flag.
    expected_weighted_bones = {name for name, _parent in expected_signature} - {"root"}
    weights = validate_weights(
        meshes[0],
        armatures[0],
        expected_weighted_bones=expected_weighted_bones,
    )
    require(bpy.data.actions, "GLB reimport did not contain the pose-test animation")
    return {
        "armatures": 1,
        "meshes": 1,
        "animations": len(bpy.data.actions),
        "vertices": weights["vertices"],
        "bytes": glb_path.stat().st_size,
        "success": True,
    }


def validate_blend(template_key: str, output_dir: Path) -> tuple[dict[str, Any], tuple[tuple[str, str | None], ...]]:
    template = TEMPLATES[template_key]
    blend_path = output_dir / f"{template.rig_name}.blend"
    glb_path = output_dir / f"{template.rig_name}.glb"
    require(blend_path.is_file(), f"missing Blender file: {blend_path}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    armature = bpy.data.objects.get(template.rig_name)
    mesh = bpy.data.objects.get(template.mesh_name)
    require(armature is not None and armature.type == "ARMATURE", f"missing armature {template.rig_name}")
    require(mesh is not None and mesh.type == "MESH", f"missing test mesh {template.mesh_name}")

    signature = armature_signature(armature)
    symmetry_pairs = validate_symmetry(armature)
    weight_result = validate_weights(mesh, armature)
    pose_result = validate_pose_tests(mesh, armature)
    glb_result = validate_glb_reimport(glb_path, signature)

    return (
        {
            "blend": blend_path.name,
            "glb": glb_path.name,
            "bone_count": len(signature),
            "symmetry_pairs": symmetry_pairs,
            "weights": weight_result,
            "pose_displacements_metres": pose_result,
            "glb_reimport": glb_result,
            "success": True,
        },
        signature,
    )


def main() -> None:
    arguments = parse_arguments()
    output_dir = arguments.output_dir.resolve()
    report_path = (arguments.report or (output_dir / "validation_report.json")).resolve()
    report: dict[str, Any] = {
        "blender_version": bpy.app.version_string,
        "configuration_controls": validate_configuration_controls(),
        "templates": {},
    }

    signatures: dict[str, tuple[tuple[str, str | None], ...]] = {}
    for key in ("male", "female"):
        result, signature = validate_blend(key, output_dir)
        report["templates"][key] = result
        signatures[key] = signature
        print(f"SPACE_NOVA_VALIDATED {TEMPLATES[key].rig_name}")

    require(signatures["male"] == signatures["female"], "male/female bone names or hierarchy differ")
    report["identical_bone_names_and_hierarchy"] = True
    report["success"] = True
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"SPACE_NOVA_VALIDATION_REPORT {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"SPACE_NOVA_VALIDATION_FAILED {type(error).__name__}: {error}", file=sys.stderr)
        raise

