"""Headless acceptance checks for the fitted Mara character."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import bpy
from mathutils import Vector


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
sys.dont_write_bytecode = True

from fit_mara import ACTION_NAME, ARMATURE_NAME, MESH_NAME, NEUTRAL_FRAME, POSE_FRAMES
from generator import FEMALE_PROPORTIONS, build_bone_specs, hierarchy_signature


WEIGHT_TOLERANCE = 1.0e-5
POSE_PROBES = {
    "shoulder": ("upper_arm.L", "upper_arm.R"),
    "elbow": ("forearm.L", "forearm.R"),
    "knee": ("shin.L", "shin.R"),
    "hip": ("thigh.L", "thigh.R"),
    "neck": ("neck", "head"),
}


class ValidationFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationFailure(message)


def blender_arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate fitted Mara outputs")
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIRECTORY / "output")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / "ai3d/assets/mara/06_game.glb",
    )
    parser.add_argument("--report", type=Path)
    return parser.parse_args(blender_arguments())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    require(ordered, "cannot calculate percentile for empty data")
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    amount = position - lower
    return float(ordered[lower] * (1.0 - amount) + ordered[upper] * amount)


def expected_signature() -> tuple[tuple[str, str | None], ...]:
    return hierarchy_signature(build_bone_specs(FEMALE_PROPORTIONS))


def armature_signature(armature: bpy.types.Object) -> tuple[tuple[str, str | None], ...]:
    return tuple(
        sorted((bone.name, bone.parent.name if bone.parent else None) for bone in armature.data.bones)
    )


def evaluated_positions(mesh: bpy.types.Object, frame: int) -> list[Vector]:
    bpy.context.scene.frame_set(frame)
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    dependency_graph.update()
    evaluated = mesh.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return [matrix @ vertex.co for vertex in evaluated_mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def validate_weights(mesh: bpy.types.Object, armature: bpy.types.Object) -> dict[str, Any]:
    modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
    require(len(modifiers) == 1, "Mara must have exactly one armature modifier")
    require(modifiers[0].object == armature, "Mara armature modifier targets the wrong object")
    require(not modifiers[0].use_deform_preserve_volume, "Blender diagnostics must match glTF linear blend skinning")

    deform_bones = {bone.name for bone in armature.data.bones if bone.use_deform}
    group_names = {group.name for group in mesh.vertex_groups}
    require(group_names == deform_bones, "Mara vertex groups do not exactly match deform bones")
    weighted_bones: set[str] = set()
    maximum_influences = 0
    minimum_weight_sum = math.inf
    maximum_weight_sum = -math.inf
    for vertex in mesh.data.vertices:
        require(vertex.groups, f"vertex {vertex.index} has no weights")
        require(len(vertex.groups) <= 4, f"vertex {vertex.index} exceeds four influences")
        maximum_influences = max(maximum_influences, len(vertex.groups))
        weight_sum = 0.0
        for membership in vertex.groups:
            name = mesh.vertex_groups[membership.group].name
            require(name in deform_bones, f"vertex {vertex.index} references non-deform group {name}")
            require(math.isfinite(membership.weight) and membership.weight > 0.0, "invalid skin weight")
            weight_sum += membership.weight
            weighted_bones.add(name)
        require(abs(weight_sum - 1.0) <= WEIGHT_TOLERANCE, f"vertex {vertex.index} weights sum to {weight_sum}")
        minimum_weight_sum = min(minimum_weight_sum, weight_sum)
        maximum_weight_sum = max(maximum_weight_sum, weight_sum)
    require(weighted_bones == deform_bones, "one or more deform bones have no weighted vertices")
    return {
        "vertices": len(mesh.data.vertices),
        "faces": len(mesh.data.polygons),
        "weighted_bones": len(weighted_bones),
        "maximum_influences": maximum_influences,
        "minimum_weight_sum": minimum_weight_sum,
        "maximum_weight_sum": maximum_weight_sum,
        "normalized": True,
    }


def probe_indices(mesh: bpy.types.Object, bone_names: tuple[str, ...]) -> list[int]:
    group_indices = {mesh.vertex_groups[name].index for name in bone_names}
    return [
        vertex.index
        for vertex in mesh.data.vertices
        if any(membership.group in group_indices and membership.weight >= 0.10 for membership in vertex.groups)
    ]


def edge_stretch_metrics(
    mesh: bpy.types.Object,
    neutral: Sequence[Vector],
    posed: Sequence[Vector],
) -> dict[str, float]:
    ratios: list[float] = []
    for edge in mesh.data.edges:
        first, second = edge.vertices
        neutral_length = (neutral[first] - neutral[second]).length
        posed_length = (posed[first] - posed[second]).length
        if neutral_length <= 1.0e-7 or posed_length <= 1.0e-7:
            continue
        ratios.append(max(posed_length / neutral_length, neutral_length / posed_length))
    require(ratios, "mesh contains no measurable edges")
    return {
        "p95": round(percentile(ratios, 0.95), 6),
        "p99": round(percentile(ratios, 0.99), 6),
        "p99_9": round(percentile(ratios, 0.999), 6),
        "maximum": round(max(ratios), 6),
    }


def validate_deformation(mesh: bpy.types.Object, armature: bpy.types.Object) -> dict[str, Any]:
    require(armature.animation_data is not None, "rig has no animation data")
    action = armature.animation_data.action
    require(action is not None and action.name == ACTION_NAME, "unexpected deformation-test action")
    marker_frames = {marker.name: marker.frame for marker in action.pose_markers}
    require(marker_frames == POSE_FRAMES, "deformation-test markers or frames changed")

    neutral = evaluated_positions(mesh, NEUTRAL_FRAME)
    height = max(point.z for point in neutral) - min(point.z for point in neutral)
    results: dict[str, Any] = {}
    for name, frame in POSE_FRAMES.items():
        posed = evaluated_positions(mesh, frame)
        require(len(posed) == len(neutral), f"{name} changed vertex count")
        require(all(all(math.isfinite(value) for value in point) for point in posed), f"{name} produced non-finite vertices")
        indices = probe_indices(mesh, POSE_PROBES[name])
        require(indices, f"{name} has no weighted probe vertices")
        displacements = [(posed[index] - neutral[index]).length for index in indices]
        maximum_displacement = max(displacements)
        mean_displacement = sum(displacements) / len(displacements)
        require(maximum_displacement >= 0.01, f"{name} did not move its probe region")
        require(maximum_displacement <= height * 0.75, f"{name} displacement is implausibly large")
        stretch = edge_stretch_metrics(mesh, neutral, posed)
        require(stretch["p99_9"] <= 3.0, f"{name} has excessive widespread edge stretch")
        results[name] = {
            "frame": frame,
            "probe_vertices": len(indices),
            "mean_displacement_metres": round(mean_displacement, 6),
            "maximum_displacement_metres": round(maximum_displacement, 6),
            "edge_stretch_ratio": stretch,
            "numeric_pass": True,
        }
    bpy.context.scene.frame_set(NEUTRAL_FRAME)
    return results


def validate_materials(mesh: bpy.types.Object) -> dict[str, Any]:
    require(len(mesh.data.uv_layers) >= 1, "Mara UV map is missing")
    require(len(mesh.data.materials) == 1, "Mara material count changed")
    material = mesh.data.materials[0]
    require(material is not None and material.use_nodes, "Mara material is not node based")
    image_nodes = [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image]
    require(len(image_nodes) == 2, "Mara's two source textures were not preserved")
    require(all(node.image.packed_file for node in image_nodes), "one or more Mara textures are not packed")
    return {
        "material": material.name,
        "uv_layers": [layer.name for layer in mesh.data.uv_layers],
        "images": [node.image.name for node in image_nodes],
        "packed_images": len(image_nodes),
    }


def validate_blend(blend_path: Path, diagnostics_dir: Path) -> tuple[dict[str, Any], str]:
    bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    armature = bpy.data.objects.get(ARMATURE_NAME)
    mesh = bpy.data.objects.get(MESH_NAME)
    require(armature is not None and armature.type == "ARMATURE", f"missing {ARMATURE_NAME}")
    require(mesh is not None and mesh.type == "MESH", f"missing {MESH_NAME}")
    require(armature_signature(armature) == expected_signature(), "Mara rig hierarchy differs from canonical 51 bones")
    require(len(armature.data.bones) == 51, "Mara rig does not contain 51 bones")
    test_meshes = [obj.name for obj in bpy.data.objects if obj.type == "MESH" and obj.get("space_nova_test_mesh")]
    require(not test_meshes, f"temporary rig geometry remains: {test_meshes}")
    require([obj for obj in bpy.data.objects if obj.type == "MESH"] == [mesh], "blend contains unexpected mesh objects")

    expected_renders = ["neutral_front", "neutral_three_quarter", *POSE_FRAMES]
    renders: dict[str, int] = {}
    for name in expected_renders:
        path = diagnostics_dir / f"{name}.png"
        require(path.is_file() and path.stat().st_size > 1000, f"missing diagnostic render {path}")
        renders[name] = path.stat().st_size

    scene = bpy.context.scene
    source_hash = str(scene.get("space_nova_source_sha256", ""))
    require(len(source_hash) == 64, "blend does not record the Mara source hash")
    return (
        {
            "bone_count": len(armature.data.bones),
            "hierarchy_preserved": True,
            "temporary_geometry_removed": True,
            "weights": validate_weights(mesh, armature),
            "materials": validate_materials(mesh),
            "deformation": validate_deformation(mesh, armature),
            "diagnostic_render_bytes": renders,
        },
        source_hash,
    )


def reset_scene() -> None:
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.wm.read_factory_settings(use_empty=True)


def validate_glb(glb_path: Path) -> dict[str, Any]:
    reset_scene()
    before = set(bpy.data.objects)
    result = bpy.ops.import_scene.gltf(filepath=str(glb_path))
    require("FINISHED" in result, "Blender failed to reimport rigged Mara GLB")
    imported = [obj for obj in bpy.data.objects if obj not in before]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    meshes = [
        obj
        for obj in imported
        if obj.type == "MESH"
        and (obj.parent in armatures or any(modifier.type == "ARMATURE" for modifier in obj.modifiers))
    ]
    require(len(armatures) == 1, f"GLB reimport found {len(armatures)} armatures")
    require(len(meshes) == 1, f"GLB reimport found {len(meshes)} meshes")
    armature = armatures[0]
    mesh = meshes[0]
    require(armature_signature(armature) == expected_signature(), "GLB reimport changed hierarchy")
    require(len(mesh.data.vertices) == 20_968, "GLB reimport changed Mara vertex count")
    require(len(mesh.data.uv_layers) >= 1, "GLB reimport dropped Mara UVs")
    require(len(mesh.data.materials) == 1, "GLB reimport changed material count")
    require(bpy.data.images, "GLB reimport contains no embedded images")
    require(bpy.data.actions, "GLB reimport contains no animation")

    # glTF does not retain Blender's use_deform flag; validate weights against
    # the canonical bone names while allowing root to remain unweighted.
    bone_names = {bone.name for bone in armature.data.bones}
    weighted_names: set[str] = set()
    maximum_influences = 0
    for vertex in mesh.data.vertices:
        require(vertex.groups, f"GLB vertex {vertex.index} has no weights")
        maximum_influences = max(maximum_influences, len(vertex.groups))
        require(len(vertex.groups) <= 4, f"GLB vertex {vertex.index} exceeds four influences")
        total = 0.0
        for membership in vertex.groups:
            name = mesh.vertex_groups[membership.group].name
            require(name in bone_names, f"GLB vertex references unknown group {name}")
            total += membership.weight
            weighted_names.add(name)
        require(abs(total - 1.0) <= WEIGHT_TOLERANCE, f"GLB vertex {vertex.index} weights sum to {total}")
    require(weighted_names == bone_names - {"root"}, "GLB omitted one or more deform bone weights")
    return {
        "armatures": 1,
        "meshes": 1,
        "bones": len(bone_names),
        "vertices": len(mesh.data.vertices),
        "uv_layers": len(mesh.data.uv_layers),
        "materials": len(mesh.data.materials),
        "images": len(bpy.data.images),
        "animations": len(bpy.data.actions),
        "maximum_influences": maximum_influences,
        "hierarchy_preserved": True,
        "success": True,
    }


def main() -> None:
    arguments = parse_arguments()
    output_dir = arguments.output_dir.expanduser().resolve()
    source = arguments.source.expanduser().resolve()
    blend_path = output_dir / "mara_venn_rigged.blend"
    glb_path = output_dir / "mara_venn_rigged.glb"
    report_path = (arguments.report or output_dir / "mara_validation_report.json").resolve()
    require(source.is_file(), f"missing source {source}")
    require(blend_path.is_file(), f"missing output {blend_path}")
    require(glb_path.is_file(), f"missing output {glb_path}")

    blend_result, recorded_source_hash = validate_blend(
        blend_path,
        output_dir / "mara_diagnostics",
    )
    actual_source_hash = sha256(source)
    require(recorded_source_hash == actual_source_hash, "source Mara GLB differs from the hash recorded during fitting")
    glb_result = validate_glb(glb_path)
    report = {
        "blender_version": bpy.app.version_string,
        "source_sha256": actual_source_hash,
        "source_preserved": True,
        "blend": blend_result,
        "glb_reimport": glb_result,
        "automated_deformation_tests_pass": True,
        "manual_visual_review": {
            "performed": True,
            "status": "requires_manual_correction",
            "notes": [
                "shoulder and inner-elbow patch seams need weight-paint cleanup",
                "hip and knee deformation expose seams between disconnected surface islands",
                "belt, holster, and thigh hard-surface pieces need rigid accessory weighting review",
                "neck rotation is serviceable but the collar/hair seam needs cleanup",
            ],
        },
        "animation_ready": False,
        "success": True,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"SPACE_NOVA_MARA_VALIDATION_REPORT {report_path}")
    print("SPACE_NOVA_MARA_VALIDATED")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"SPACE_NOVA_MARA_VALIDATION_FAILED {type(error).__name__}: {error}", file=sys.stderr)
        raise
