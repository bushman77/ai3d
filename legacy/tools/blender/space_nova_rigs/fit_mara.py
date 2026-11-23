"""Fit the canonical Space Nova female rig to Mara and produce skinned assets.

Run this file with Blender 4.1 in background mode.  The source GLB and female
template are opened read-only; only files below ``--output-dir`` are written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Iterable, Sequence

import bpy
from mathutils import Matrix, Vector


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
sys.dont_write_bytecode = True

from generator import hierarchy_signature, build_bone_specs, FEMALE_PROPORTIONS


ARMATURE_NAME = "SpaceNovaFemaleRig"
MESH_NAME = "MaraVenn"
ACTION_NAME = "MaraDeformationTests"
NEUTRAL_FRAME = 1
POSE_FRAMES = {
    "shoulder": 10,
    "elbow": 20,
    "knee": 30,
    "hip": 40,
    "neck": 50,
}
OUTPUT_BLEND = "mara_venn_rigged.blend"
OUTPUT_GLB = "mara_venn_rigged.glb"


class FitFailure(RuntimeError):
    """Raised when an input cannot satisfy the rigging contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FitFailure(message)


def blender_arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fit SpaceNovaFemaleRig to Mara")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / "ai3d/assets/mara/06_game.glb",
    )
    parser.add_argument(
        "--female-rig",
        type=Path,
        default=SCRIPT_DIRECTORY / "output/SpaceNovaFemaleRig.blend",
    )
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIRECTORY / "output")
    parser.add_argument("--render-size", type=int, default=700)
    return parser.parse_args(blender_arguments())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: Sequence[float], fraction: float) -> float:
    require(values, "cannot calculate a percentile of an empty collection")
    ordered = sorted(values)
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    blend = position - lower
    return float(ordered[lower] * (1.0 - blend) + ordered[upper] * blend)


def median_vector(points: Sequence[Vector]) -> Vector:
    require(points, "cannot calculate a median point of an empty collection")
    return Vector(tuple(statistics.median(point[axis] for point in points) for axis in range(3)))


def vector_payload(vector: Vector) -> list[float]:
    return [round(float(component), 7) for component in vector]


def armature_signature(armature: bpy.types.Object) -> tuple[tuple[str, str | None], ...]:
    return tuple(
        sorted((bone.name, bone.parent.name if bone.parent else None) for bone in armature.data.bones)
    )


def expected_signature() -> tuple[tuple[str, str | None], ...]:
    return hierarchy_signature(build_bone_specs(FEMALE_PROPORTIONS))


def remove_object(obj: bpy.types.Object) -> None:
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and getattr(data, "users", 0) == 0:
        data_collection = getattr(bpy.data, f"{data.__class__.__name__.lower()}s", None)
        if data_collection is not None:
            data_collection.remove(data)


def prepare_template(rig_path: Path) -> bpy.types.Object:
    bpy.ops.wm.open_mainfile(filepath=str(rig_path), load_ui=False)
    armature = bpy.data.objects.get(ARMATURE_NAME)
    require(armature is not None and armature.type == "ARMATURE", f"missing {ARMATURE_NAME}")
    require(armature_signature(armature) == expected_signature(), "female template hierarchy is not canonical")

    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and (obj.get("space_nova_test_mesh") or "TestMesh" in obj.name):
            remove_object(obj)

    armature.animation_data_clear()
    for action in list(bpy.data.actions):
        if action.name == "SpaceNovaPoseTests":
            bpy.data.actions.remove(action)
    for material in list(bpy.data.materials):
        if "TestMaterial" in material.name and material.users == 0:
            bpy.data.materials.remove(material)
    return armature


def import_mara(source_path: Path) -> bpy.types.Object:
    before = set(bpy.data.objects)
    result = bpy.ops.import_scene.gltf(filepath=str(source_path))
    require("FINISHED" in result, "Blender failed to import Mara's GLB")
    imported = [obj for obj in bpy.data.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    require(len(meshes) == 1, f"Mara source must import exactly one mesh, found {len(meshes)}")
    require(not armatures, "Mara source unexpectedly contains an armature")
    mesh = meshes[0]
    mesh.name = MESH_NAME
    mesh.data.name = f"{MESH_NAME}Geometry"
    mesh["space_nova_character"] = "Mara Venn"
    mesh["space_nova_source_asset"] = source_path.name
    return mesh


def world_vertices(mesh: bpy.types.Object) -> list[Vector]:
    return [mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices]


def local_depth(points: Sequence[Vector], x: float, z: float, radius: float, fallback: float) -> float:
    radius_squared = radius * radius
    values = [
        point.y
        for point in points
        if (point.x - x) * (point.x - x) + (point.z - z) * (point.z - z) <= radius_squared
    ]
    if len(values) < 8:
        return fallback
    # The midpoint of robust front/back percentiles follows the limb or torso
    # core better than the mean when belts, pouches, hair, or boots are present.
    return (percentile(values, 0.12) + percentile(values, 0.88)) * 0.5


def infer_landmarks(mesh: bpy.types.Object) -> tuple[dict[str, Vector], dict[str, float]]:
    points = world_vertices(mesh)
    require(len(points) >= 1000, "Mara mesh is unexpectedly small")
    minimum = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    maximum = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    height = maximum.z - minimum.z
    require(1.5 <= height <= 2.5, f"Mara height {height:.4f} m is outside the expected human range")

    center_x = (minimum.x + maximum.x) * 0.5
    center_y = (percentile([point.y for point in points], 0.05) + percentile([point.y for point in points], 0.95)) * 0.5
    floor_z = minimum.z
    hip_z = floor_z + height * 0.515
    knee_z = floor_z + height * 0.300
    ankle_z = floor_z + height * 0.110
    shoulder_z = floor_z + height * 0.780
    neck_base_z = floor_z + height * 0.830
    head_base_z = floor_z + height * 0.855
    head_tail_z = floor_z + height * 0.965
    hip_offset = height * 0.070
    shoulder_offset = height * 0.103

    def core_point(x: float, z: float, radius: float = 0.045) -> Vector:
        return Vector((x, local_depth(points, x, z, height * radius, center_y), z))

    landmarks: dict[str, Vector] = {
        "root": Vector((center_x, center_y, floor_z)),
        "pelvis": core_point(center_x, hip_z),
        "spine_base": core_point(center_x, hip_z + height * 0.060),
        "spine_01": core_point(center_x, hip_z + height * 0.124),
        "spine_02": core_point(center_x, hip_z + height * 0.207),
        "chest": core_point(center_x, neck_base_z),
        "neck": core_point(center_x, head_base_z, 0.035),
        "head": core_point(center_x, head_tail_z, 0.055),
    }

    for suffix, side in ((".L", 1.0), (".R", -1.0)):
        shoulder_x = center_x + side * shoulder_offset
        shoulder = core_point(shoulder_x, shoulder_z, 0.04)
        initial_direction = Vector((side * 0.46, 0.0, -0.89)).normalized()
        candidates = [
            point
            for point in points
            if side * (point.x - center_x) > height * 0.12
            and floor_z + height * 0.40 < point.z < shoulder_z + height * 0.05
        ]
        require(len(candidates) >= 100, f"not enough vertices to infer the {suffix} arm")
        projections = [(point - shoulder).dot(initial_direction) for point in candidates]
        threshold = percentile(projections, 0.992)
        distal_cloud = [point for point, projection in zip(candidates, projections) if projection >= threshold]
        distal = median_vector(distal_cloud)
        distal.y = local_depth(points, distal.x, distal.z, height * 0.035, distal.y)
        require((distal - shoulder).length > height * 0.25, f"inferred {suffix} arm is too short")

        wrist = shoulder.lerp(distal, 0.735)
        elbow = shoulder.lerp(wrist, 0.515)
        palm = wrist.lerp(distal, 0.48)
        elbow.y = local_depth(points, elbow.x, elbow.z, height * 0.035, elbow.y)
        wrist.y = local_depth(points, wrist.x, wrist.z, height * 0.030, wrist.y)
        palm.y = local_depth(points, palm.x, palm.z, height * 0.025, palm.y)

        hip = core_point(center_x + side * hip_offset, hip_z, 0.04)
        knee = core_point(center_x + side * height * 0.064, knee_z, 0.035)
        ankle = core_point(center_x + side * height * 0.062, ankle_z, 0.030)
        ball = Vector((ankle.x, minimum.y + height * 0.035, floor_z + height * 0.035))
        toe = Vector((ankle.x, minimum.y, floor_z + height * 0.018))

        landmarks.update(
            {
                f"shoulder{suffix}": shoulder,
                f"elbow{suffix}": elbow,
                f"wrist{suffix}": wrist,
                f"palm{suffix}": palm,
                f"hand_tip{suffix}": distal,
                f"hip{suffix}": hip,
                f"knee{suffix}": knee,
                f"ankle{suffix}": ankle,
                f"ball{suffix}": ball,
                f"toe{suffix}": toe,
            }
        )

    measurements = {
        "height": height,
        "center_x": center_x,
        "center_y": center_y,
        "bounds_min_x": minimum.x,
        "bounds_min_y": minimum.y,
        "bounds_min_z": minimum.z,
        "bounds_max_x": maximum.x,
        "bounds_max_y": maximum.y,
        "bounds_max_z": maximum.z,
        "shoulder_width": (landmarks["shoulder.L"] - landmarks["shoulder.R"]).length,
        "hip_width": (landmarks["hip.L"] - landmarks["hip.R"]).length,
        "left_arm_length": (landmarks["shoulder.L"] - landmarks["elbow.L"]).length
        + (landmarks["elbow.L"] - landmarks["wrist.L"]).length,
        "right_arm_length": (landmarks["shoulder.R"] - landmarks["elbow.R"]).length
        + (landmarks["elbow.R"] - landmarks["wrist.R"]).length,
        "left_leg_length": (landmarks["hip.L"] - landmarks["knee.L"]).length
        + (landmarks["knee.L"] - landmarks["ankle.L"]).length,
        "right_leg_length": (landmarks["hip.R"] - landmarks["knee.R"]).length
        + (landmarks["knee.R"] - landmarks["ankle.R"]).length,
    }
    return landmarks, measurements


def hand_bone_positions(
    suffix: str,
    side: float,
    landmarks: dict[str, Vector],
    height: float,
) -> dict[str, tuple[Vector, Vector]]:
    wrist = landmarks[f"wrist{suffix}"]
    palm = landmarks[f"palm{suffix}"]
    distal = landmarks[f"hand_tip{suffix}"]
    direction = (distal - wrist).normalized()
    across = Vector((-direction.z, 0.0, direction.x)).normalized() * side
    remaining = max((distal - palm).length, height * 0.035)
    positions: dict[str, tuple[Vector, Vector]] = {}
    fingers = (
        ("index", -0.75, 0.96, -7.0),
        ("middle", -0.25, 1.02, -2.0),
        ("ring", 0.28, 0.95, 3.0),
        ("pinky", 0.78, 0.82, 8.0),
    )
    for finger, spread, length_factor, fan_degrees in fingers:
        root = palm + across * (spread * height * 0.010)
        fan = Matrix.Rotation(math.radians(fan_degrees * side), 4, "Y") @ direction
        total = remaining * length_factor
        segment_lengths = (total * 0.42, total * 0.33, total * 0.25)
        segment_head = root
        for segment_index, segment_length in enumerate(segment_lengths, start=1):
            segment_tail = segment_head + fan * segment_length
            positions[f"{finger}_{segment_index:02d}{suffix}"] = (segment_head, segment_tail)
            segment_head = segment_tail

    thumb_root = wrist.lerp(palm, 0.34) - across * height * 0.014
    thumb_direction = (direction * 0.64 - across * 0.77).normalized()
    thumb_mid = thumb_root + thumb_direction * height * 0.036
    thumb_tip = thumb_mid + thumb_direction * height * 0.030
    positions[f"thumb_01{suffix}"] = (thumb_root, thumb_mid)
    positions[f"thumb_02{suffix}"] = (thumb_mid, thumb_tip)
    return positions


def fitted_bone_positions(landmarks: dict[str, Vector], height: float) -> dict[str, tuple[Vector, Vector]]:
    root = landmarks["root"]
    pelvis = landmarks["pelvis"]
    spine_base = landmarks["spine_base"]
    spine_01 = landmarks["spine_01"]
    spine_02 = landmarks["spine_02"]
    chest = landmarks["chest"]
    neck = landmarks["neck"]
    head = landmarks["head"]
    positions: dict[str, tuple[Vector, Vector]] = {
        "root": (root, root + Vector((0.0, 0.0, height * 0.080))),
        "pelvis": (pelvis - Vector((0.0, 0.0, height * 0.048)), spine_base),
        "spine_01": (spine_base, spine_01),
        "spine_02": (spine_01, spine_02),
        "chest": (spine_02, chest),
        "neck": (chest, neck),
        "head": (neck, head),
    }

    for suffix, side in ((".L", 1.0), (".R", -1.0)):
        shoulder = landmarks[f"shoulder{suffix}"]
        elbow = landmarks[f"elbow{suffix}"]
        wrist = landmarks[f"wrist{suffix}"]
        palm = landmarks[f"palm{suffix}"]
        hip = landmarks[f"hip{suffix}"]
        knee = landmarks[f"knee{suffix}"]
        ankle = landmarks[f"ankle{suffix}"]
        ball = landmarks[f"ball{suffix}"]
        toe = landmarks[f"toe{suffix}"]
        clavicle_head = chest.lerp(shoulder, 0.14)
        clavicle_head.z -= height * 0.020
        positions.update(
            {
                f"clavicle{suffix}": (clavicle_head, shoulder),
                f"upper_arm{suffix}": (shoulder, elbow),
                f"forearm{suffix}": (elbow, wrist),
                f"hand{suffix}": (wrist, palm),
                f"thigh{suffix}": (hip, knee),
                f"shin{suffix}": (knee, ankle),
                f"foot{suffix}": (ankle, ball),
                f"toe{suffix}": (ball, toe),
            }
        )
        positions.update(hand_bone_positions(suffix, side, landmarks, height))
    return positions


def fit_armature(
    armature: bpy.types.Object,
    positions_world: dict[str, tuple[Vector, Vector]],
) -> None:
    require(set(positions_world) == {bone.name for bone in armature.data.bones}, "fitted bone set is incomplete")
    original_signature = armature_signature(armature)
    world_to_armature = armature.matrix_world.inverted()
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, (head_world, tail_world) in positions_world.items():
        edit_bone = armature.data.edit_bones[bone_name]
        edit_bone.head = world_to_armature @ head_world
        edit_bone.tail = world_to_armature @ tail_world
        edit_bone.roll = 0.0
    bpy.ops.object.mode_set(mode="OBJECT")
    require(armature_signature(armature) == original_signature, "fitting changed the canonical hierarchy")
    armature.show_in_front = True
    armature["space_nova_fitted_character"] = "Mara Venn"
    armature["space_nova_fitting_method"] = "mesh bounds plus A-pose landmark inference"


def point_segment_distance(point: Vector, head: Vector, tail: Vector) -> float:
    segment = tail - head
    length_squared = segment.length_squared
    if length_squared <= 1.0e-12:
        return (point - head).length
    factor = max(0.0, min(1.0, (point - head).dot(segment) / length_squared))
    return (point - head.lerp(tail, factor)).length


def side_penalty(point: Vector, bone_name: str, center_x: float, height: float) -> float:
    if bone_name.endswith(".L") and point.x < center_x - height * 0.008:
        return height
    if bone_name.endswith(".R") and point.x > center_x + height * 0.008:
        return height
    return 0.0


def smooth_assignments(
    mesh: bpy.types.Object,
    assignments: list[list[tuple[str, float]]],
    iterations: int = 4,
) -> list[list[tuple[str, float]]]:
    """Blend weights only across real mesh edges and retain four influences.

    This softens the arm/torso classification boundary without leaking glove
    motion into disconnected holsters that happen to occupy nearby space.
    """

    neighbours: list[set[int]] = [set() for _vertex in mesh.data.vertices]
    for edge in mesh.data.edges:
        first, second = edge.vertices
        neighbours[first].add(second)
        neighbours[second].add(first)

    current = assignments
    for _iteration in range(iterations):
        updated: list[list[tuple[str, float]]] = []
        for vertex_index, vertex_weights in enumerate(current):
            adjacent = neighbours[vertex_index]
            if not adjacent:
                updated.append(vertex_weights)
                continue
            totals: dict[str, float] = {}
            for bone_name, weight in vertex_weights:
                totals[bone_name] = totals.get(bone_name, 0.0) + weight * 0.58
            neighbour_scale = 0.42 / len(adjacent)
            for neighbour_index in adjacent:
                for bone_name, weight in current[neighbour_index]:
                    totals[bone_name] = totals.get(bone_name, 0.0) + weight * neighbour_scale
            strongest = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]
            weight_total = sum(weight for _bone_name, weight in strongest)
            updated.append([(bone_name, weight / weight_total) for bone_name, weight in strongest])
        current = updated
    result: list[list[tuple[str, float]]] = []
    for vertex_weights in current:
        strongest = sorted(vertex_weights, key=lambda item: item[1], reverse=True)[:4]
        weight_total = sum(weight for _bone_name, weight in strongest)
        result.append([(bone_name, weight / weight_total) for bone_name, weight in strongest])
    return result


def synchronize_split_vertices(
    mesh: bpy.types.Object,
    assignments: list[list[tuple[str, float]]],
) -> list[list[tuple[str, float]]]:
    """Give UV/normal-split copies at the same position identical weights."""

    position_groups: dict[tuple[float, float, float], list[int]] = {}
    for vertex in mesh.data.vertices:
        key = tuple(round(float(component), 5) for component in vertex.co)
        position_groups.setdefault(key, []).append(vertex.index)

    result = [list(vertex_weights) for vertex_weights in assignments]
    for indices in position_groups.values():
        if len(indices) < 2:
            continue
        totals: dict[str, float] = {}
        for vertex_index in indices:
            for bone_name, weight in assignments[vertex_index]:
                totals[bone_name] = totals.get(bone_name, 0.0) + weight / len(indices)
        strongest = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:4]
        total = sum(weight for _bone_name, weight in strongest)
        synchronized = [(bone_name, weight / total) for bone_name, weight in strongest]
        for vertex_index in indices:
            result[vertex_index] = synchronized
    return result


def calculate_weights(
    mesh: bpy.types.Object,
    armature: bpy.types.Object,
    center_x: float,
    height: float,
) -> tuple[list[list[tuple[str, float]]], dict[str, int]]:
    segments = {
        bone.name: (
            armature.matrix_world @ bone.head_local,
            armature.matrix_world @ bone.tail_local,
        )
        for bone in armature.data.bones
        if bone.use_deform
    }
    arm_bones = {
        suffix: {
            bone_name
            for bone_name in segments
            if bone_name.endswith(suffix)
            and bone_name.split(".", 1)[0]
            not in {"thigh", "shin", "foot", "toe"}
        }
        for suffix in (".L", ".R")
    }
    hip_z = (segments["thigh.L"][0].z + segments["thigh.R"][0].z) * 0.5
    points = world_vertices(mesh)

    def overlap_penalty(point: Vector, bone_name: str) -> float:
        """Continuously separate low hands from nearby hip equipment."""

        for suffix, side in ((".L", 1.0), (".R", -1.0)):
            if bone_name not in arm_bones[suffix]:
                continue
            lateral = side * (point.x - center_x)
            inner_factor = max(
                0.0,
                min(1.0, (height * 0.20 - lateral) / (height * 0.08)),
            )
            low_factor = max(
                0.0,
                min(1.0, (hip_z + height * 0.10 - point.z) / (height * 0.20)),
            )
            return height * 0.60 * inner_factor * low_factor
        return 0.0

    assignments: list[list[tuple[str, float]]] = []
    influence_counts = {bone_name: 0 for bone_name in segments}
    blend_width = height * 0.026
    for point in points:
        # Distance and penalties are continuous in space.  This keeps the
        # source's many split surface patches together under deformation.
        distances = sorted(
            (
                point_segment_distance(point, head, tail)
                + side_penalty(point, bone_name, center_x, height)
                + overlap_penalty(point, bone_name),
                bone_name,
            )
            for bone_name, (head, tail) in segments.items()
        )[:4]
        minimum_distance = distances[0][0]
        raw = [
            math.exp(-(distance - minimum_distance) / blend_width)
            / max(distance + height * 0.010, height * 0.003)
            for distance, _bone_name in distances
        ]
        raw_total = sum(raw)
        vertex_weights = [
            (bone_name, value / raw_total)
            for value, (_distance, bone_name) in zip(raw, distances)
            if value / raw_total >= 0.005
        ]
        normalized_total = sum(weight for _bone_name, weight in vertex_weights)
        vertex_weights = [(bone_name, weight / normalized_total) for bone_name, weight in vertex_weights]
        assignments.append(vertex_weights)
        for bone_name, _weight in vertex_weights:
            influence_counts[bone_name] += 1

    assignments = smooth_assignments(mesh, assignments, iterations=12)
    assignments = synchronize_split_vertices(mesh, assignments)
    assignments = smooth_assignments(mesh, assignments, iterations=6)
    assignments = synchronize_split_vertices(mesh, assignments)
    influence_counts = {bone_name: 0 for bone_name in segments}
    for vertex_weights in assignments:
        for bone_name, _weight in vertex_weights:
            influence_counts[bone_name] += 1

    # A tiny finger segment can fall between duplicated UV-seam vertices.  Give
    # any otherwise unused deform bone its closest surface vertex, while still
    # retaining the four-influence export contract.
    points = world_vertices(mesh)
    for bone_name, count in list(influence_counts.items()):
        if count:
            continue
        head, tail = segments[bone_name]
        closest_index = min(
            range(len(points)),
            key=lambda index: point_segment_distance(points[index], head, tail),
        )
        retained = assignments[closest_index][:3]
        retained = [(name, weight * 0.75) for name, weight in retained]
        retained.append((bone_name, 0.25))
        total = sum(weight for _name, weight in retained)
        assignments[closest_index] = [(name, weight / total) for name, weight in retained]
        influence_counts[bone_name] = 1

    return assignments, influence_counts


def bind_mesh(
    mesh: bpy.types.Object,
    armature: bpy.types.Object,
    measurements: dict[str, float],
) -> dict[str, int | float]:
    mesh.parent = None
    for modifier in list(mesh.modifiers):
        mesh.modifiers.remove(modifier)
    mesh.vertex_groups.clear()
    assignments, influence_counts = calculate_weights(
        mesh,
        armature,
        measurements["center_x"],
        measurements["height"],
    )
    groups = {
        bone.name: mesh.vertex_groups.new(name=bone.name)
        for bone in armature.data.bones
        if bone.use_deform
    }
    maximum_influences = 0
    for vertex_index, vertex_weights in enumerate(assignments):
        maximum_influences = max(maximum_influences, len(vertex_weights))
        for bone_name, weight in vertex_weights:
            groups[bone_name].add([vertex_index], weight, "REPLACE")

    modifier = mesh.modifiers.new(name="SpaceNovaArmature", type="ARMATURE")
    modifier.object = armature
    # glTF/Three.js use linear blend skinning, so diagnostics must exercise
    # that same deformation model rather than Blender-only dual quaternions.
    modifier.use_deform_preserve_volume = False
    mesh.parent = armature
    mesh.matrix_parent_inverse = armature.matrix_world.inverted()
    mesh["space_nova_binding"] = "deterministic nearest-segment four-influence weights"
    return {
        "vertices": len(mesh.data.vertices),
        "faces": len(mesh.data.polygons),
        "weighted_bones": sum(1 for count in influence_counts.values() if count > 0),
        "maximum_influences": maximum_influences,
    }


def create_deformation_action(armature: bpy.types.Object) -> bpy.types.Action:
    action = bpy.data.actions.new(name=ACTION_NAME)
    action.use_fake_user = True
    armature.animation_data_create()
    armature.animation_data.action = action

    for frame in (NEUTRAL_FRAME, *POSE_FRAMES.values()):
        for pose_bone in armature.pose.bones:
            pose_bone.rotation_mode = "XYZ"
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.rotation_euler = (0.0, 0.0, 0.0)

        if frame == POSE_FRAMES["shoulder"]:
            armature.pose.bones["upper_arm.L"].rotation_euler.x = math.radians(20.0)
            armature.pose.bones["upper_arm.R"].rotation_euler.x = math.radians(-20.0)
        elif frame == POSE_FRAMES["elbow"]:
            armature.pose.bones["forearm.L"].rotation_euler.x = math.radians(72.0)
            armature.pose.bones["forearm.R"].rotation_euler.x = math.radians(-72.0)
        elif frame == POSE_FRAMES["knee"]:
            armature.pose.bones["thigh.L"].rotation_euler.x = math.radians(-10.0)
            armature.pose.bones["thigh.R"].rotation_euler.x = math.radians(-10.0)
            armature.pose.bones["shin.L"].rotation_euler.x = math.radians(62.0)
            armature.pose.bones["shin.R"].rotation_euler.x = math.radians(62.0)
        elif frame == POSE_FRAMES["hip"]:
            armature.pose.bones["thigh.L"].rotation_euler.x = math.radians(-28.0)
            armature.pose.bones["thigh.R"].rotation_euler.x = math.radians(20.0)
            armature.pose.bones["pelvis"].rotation_euler.z = math.radians(7.0)
        elif frame == POSE_FRAMES["neck"]:
            armature.pose.bones["neck"].rotation_euler.y = math.radians(20.0)
            armature.pose.bones["head"].rotation_euler.y = math.radians(18.0)

        for pose_bone in armature.pose.bones:
            pose_bone.keyframe_insert(data_path="location", frame=frame, group=pose_bone.name)
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=pose_bone.name)

    for name, frame in POSE_FRAMES.items():
        action.pose_markers.new(name).frame = frame
    for fcurve in action.fcurves:
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = "CONSTANT"
    bpy.context.scene.frame_start = NEUTRAL_FRAME
    bpy.context.scene.frame_end = max(POSE_FRAMES.values())
    bpy.context.scene.frame_set(NEUTRAL_FRAME)
    return action


def configure_diagnostic_scene(height: float, render_size: int) -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = render_size
    scene.render.resolution_y = round(render_size * 1.28)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.008, 0.012, 0.018, 1.0)
    background.inputs["Strength"].default_value = 0.32

    camera_data = bpy.data.cameras.new("MaraDiagnosticCamera")
    camera = bpy.data.objects.new("MaraDiagnosticCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = height * 1.12
    scene.camera = camera

    lights = (
        ("MaraDiagnosticKey", (2.8, -3.5, 3.0), 1050.0, 4.0, (0.78, 0.88, 1.0)),
        ("MaraDiagnosticFill", (-2.5, -2.0, 1.0), 720.0, 3.0, (0.55, 0.78, 1.0)),
        ("MaraDiagnosticRim", (0.5, 2.4, 2.5), 1100.0, 3.0, (0.4, 0.7, 1.0)),
    )
    for name, location, energy, size, color in lights:
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = size
        light_data.color = color
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = ((Vector((0.0, 0.0, 0.0)) - light.location).to_track_quat("-Z", "Y")).to_euler()
    return camera


def aim_camera(camera: bpy.types.Object, location: tuple[float, float, float], target: Vector) -> None:
    camera.location = location
    camera.rotation_euler = ((target - camera.location).to_track_quat("-Z", "Y")).to_euler()


def render_diagnostics(
    output_dir: Path,
    camera: bpy.types.Object,
    measurements: dict[str, float],
) -> list[str]:
    diagnostics_dir = output_dir / "mara_diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    target = Vector((measurements["center_x"], measurements["center_y"], -0.02))
    distance = measurements["height"] * 2.1
    renders = [
        ("neutral_front", NEUTRAL_FRAME, (0.0, -distance, 0.0)),
        ("neutral_three_quarter", NEUTRAL_FRAME, (distance * 0.58, -distance, 0.12)),
        ("shoulder", POSE_FRAMES["shoulder"], (distance * 0.38, -distance, 0.05)),
        ("elbow", POSE_FRAMES["elbow"], (distance * 0.38, -distance, 0.05)),
        ("knee", POSE_FRAMES["knee"], (distance * 0.38, -distance, 0.05)),
        ("hip", POSE_FRAMES["hip"], (distance * 0.38, -distance, 0.05)),
        ("neck", POSE_FRAMES["neck"], (distance * 0.38, -distance, 0.05)),
    ]
    paths: list[str] = []
    for label, frame, location in renders:
        scene.frame_set(frame)
        aim_camera(camera, location, target)
        path = diagnostics_dir / f"{label}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths.append(str(path))
    scene.frame_set(NEUTRAL_FRAME)
    return paths


def export_outputs(
    armature: bpy.types.Object,
    mesh: bpy.types.Object,
    output_dir: Path,
) -> tuple[Path, Path]:
    blend_path = output_dir / OUTPUT_BLEND
    glb_path = output_dir / OUTPUT_GLB
    bpy.context.scene.frame_set(NEUTRAL_FRAME)
    bpy.ops.file.pack_all()
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=True,
        export_skins=True,
        export_animations=True,
        export_yup=True,
        export_apply=False,
    )
    return blend_path, glb_path


def material_report(mesh: bpy.types.Object) -> dict[str, object]:
    image_nodes = []
    for material in mesh.data.materials:
        if material and material.use_nodes:
            image_nodes.extend(node for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
    return {
        "materials": [material.name for material in mesh.data.materials if material],
        "uv_layers": [layer.name for layer in mesh.data.uv_layers],
        "image_textures": [node.image.name for node in image_nodes if node.image],
        "packed_images": sum(1 for node in image_nodes if node.image and node.image.packed_file),
    }


def main() -> None:
    arguments = parse_arguments()
    source = arguments.source.expanduser().resolve()
    female_rig = arguments.female_rig.expanduser().resolve()
    output_dir = arguments.output_dir.expanduser().resolve()
    require(source.is_file(), f"missing Mara source: {source}")
    require(female_rig.is_file(), f"missing female rig: {female_rig}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_hash_before = sha256(source)
    rig_hash_before = sha256(female_rig)

    armature = prepare_template(female_rig)
    mesh = import_mara(source)
    original_mesh = {
        "vertices": len(mesh.data.vertices),
        "faces": len(mesh.data.polygons),
        "uv_layers": [layer.name for layer in mesh.data.uv_layers],
        "materials": [material.name for material in mesh.data.materials if material],
    }
    landmarks, measurements = infer_landmarks(mesh)
    positions = fitted_bone_positions(landmarks, measurements["height"])
    fit_armature(armature, positions)
    binding = bind_mesh(mesh, armature, measurements)
    action = create_deformation_action(armature)
    camera = configure_diagnostic_scene(measurements["height"], arguments.render_size)
    diagnostic_paths = render_diagnostics(output_dir, camera, measurements)

    scene = bpy.context.scene
    scene.name = "MaraVennRiggedScene"
    scene["space_nova_character"] = "Mara Venn"
    scene["space_nova_source_sha256"] = source_hash_before
    scene["space_nova_template_sha256"] = rig_hash_before
    scene["space_nova_bone_count"] = len(armature.data.bones)
    scene["space_nova_pose_test_frames"] = json.dumps(POSE_FRAMES, sort_keys=True)
    scene["space_nova_landmarks"] = json.dumps(
        {name: vector_payload(point) for name, point in landmarks.items()}, sort_keys=True
    )
    blend_path, glb_path = export_outputs(armature, mesh, output_dir)

    require(sha256(source) == source_hash_before, "Mara source changed during fitting")
    require(sha256(female_rig) == rig_hash_before, "female template changed during fitting")
    report = {
        "blender_version": bpy.app.version_string,
        "source": str(source),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": sha256(source),
        "source_preserved": True,
        "female_rig": str(female_rig),
        "female_rig_sha256_before": rig_hash_before,
        "female_rig_sha256_after": sha256(female_rig),
        "female_rig_preserved": True,
        "outputs": {
            "blend": str(blend_path),
            "blend_bytes": blend_path.stat().st_size,
            "glb": str(glb_path),
            "glb_bytes": glb_path.stat().st_size,
        },
        "original_mesh": original_mesh,
        "materials_after_binding": material_report(mesh),
        "measurements_metres": {key: round(value, 7) for key, value in measurements.items()},
        "landmarks_metres": {name: vector_payload(point) for name, point in landmarks.items()},
        "binding": binding,
        "bone_count": len(armature.data.bones),
        "hierarchy_preserved": armature_signature(armature) == expected_signature(),
        "action": action.name,
        "pose_frames": POSE_FRAMES,
        "diagnostic_renders": diagnostic_paths,
        "manual_corrections_applied": [],
        "manual_corrections_required": [
            "shoulder and inner-elbow patch seams",
            "hip and knee disconnected-island seams",
            "rigid belt, holster, and thigh-panel weighting",
            "collar and hair response during neck rotation",
        ],
        "animation_ready": False,
        "success": True,
    }
    report_path = output_dir / "mara_fit_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"SPACE_NOVA_MARA_FIT_REPORT {report_path}")
    print(f"SPACE_NOVA_MARA_FITTED {blend_path}")
    print(f"SPACE_NOVA_MARA_EXPORTED {glb_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"SPACE_NOVA_MARA_FIT_FAILED {type(error).__name__}: {error}", file=sys.stderr)
        raise
