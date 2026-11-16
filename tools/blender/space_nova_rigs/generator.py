"""Reusable Space Nova humanoid rig generator for Blender 4.1.

The module deliberately uses only Blender's bundled Python API.  It builds a
deform skeleton, a lightweight weighted mannequin, and a small pose-test
action from a :class:`HumanoidProportions` value.  The same builder is used for
both supplied templates so their bone names and hierarchy cannot drift.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import bpy
from mathutils import Vector


GENERATOR_VERSION = "1.0.0"
NEUTRAL_FRAME = 1
POSE_FRAMES = {
    "shoulder_rotation": 10,
    "elbow_bending": 20,
    "knee_bending": 30,
    "hip_movement": 40,
    "head_turning": 50,
}


@dataclass(frozen=True)
class HumanoidProportions:
    """Anatomical dimensions in Blender metres.

    ``arm_length`` is shoulder-to-wrist distance and ``leg_length`` is
    hip-to-ankle distance.  The hand and foot dimensions are derived from the
    head dimensions so the required controls remain compact and predictable.
    """

    shoulder_width: float
    pelvis_width: float
    torso_length: float
    arm_length: float
    leg_length: float
    neck_length: float
    head_width: float
    head_depth: float
    head_height: float

    def validate(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{item.name} must be a positive finite number")

        if self.shoulder_width <= self.pelvis_width * 0.75:
            raise ValueError("shoulder_width is implausibly narrow for the pelvis")
        if self.head_height <= self.neck_length * 1.1:
            raise ValueError("head_height must be greater than neck_length")

    def with_overrides(self, overrides: Mapping[str, float]) -> "HumanoidProportions":
        allowed = {item.name for item in fields(self)}
        unknown = set(overrides) - allowed
        if unknown:
            raise ValueError(f"unknown proportion keys: {', '.join(sorted(unknown))}")

        updated = replace(self, **{key: float(value) for key, value in overrides.items()})
        updated.validate()
        return updated


MALE_PROPORTIONS = HumanoidProportions(
    shoulder_width=0.48,
    pelvis_width=0.34,
    torso_length=0.56,
    arm_length=0.64,
    leg_length=0.91,
    neck_length=0.13,
    head_width=0.17,
    head_depth=0.205,
    head_height=0.24,
)

FEMALE_PROPORTIONS = HumanoidProportions(
    shoulder_width=0.42,
    pelvis_width=0.36,
    torso_length=0.52,
    arm_length=0.60,
    leg_length=0.86,
    neck_length=0.12,
    head_width=0.16,
    head_depth=0.195,
    head_height=0.23,
)


@dataclass(frozen=True)
class BoneSpec:
    name: str
    head: tuple[float, float, float]
    tail: tuple[float, float, float]
    parent: str | None
    connected: bool = False
    deform: bool = True


@dataclass(frozen=True)
class TemplateSpec:
    rig_name: str
    mesh_name: str
    proportions: HumanoidProportions
    color: tuple[float, float, float, float]


TEMPLATES = {
    "male": TemplateSpec(
        rig_name="SpaceNovaMaleRig",
        mesh_name="SpaceNovaMaleTestMesh",
        proportions=MALE_PROPORTIONS,
        color=(0.055, 0.32, 0.64, 1.0),
    ),
    "female": TemplateSpec(
        rig_name="SpaceNovaFemaleRig",
        mesh_name="SpaceNovaFemaleTestMesh",
        proportions=FEMALE_PROPORTIONS,
        color=(0.62, 0.11, 0.36, 1.0),
    ),
}


def load_overrides(path: str | Path | None) -> dict[str, float]:
    if path is None:
        return {}

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("proportion override JSON must contain an object")
    return payload


def _v(vector: Vector) -> tuple[float, float, float]:
    return tuple(float(component) for component in vector)


def build_bone_specs(proportions: HumanoidProportions) -> list[BoneSpec]:
    """Return the canonical Space Nova skeleton in a neutral A-pose."""

    proportions.validate()
    specs: list[BoneSpec] = []

    def add(
        name: str,
        head: Sequence[float] | Vector,
        tail: Sequence[float] | Vector,
        parent: str | None,
        *,
        connected: bool = False,
        deform: bool = True,
    ) -> None:
        specs.append(
            BoneSpec(
                name=name,
                head=_v(Vector(head)),
                tail=_v(Vector(tail)),
                parent=parent,
                connected=connected,
                deform=deform,
            )
        )

    ankle_z = max(0.075, proportions.head_height * 0.36)
    hip_z = ankle_z + proportions.leg_length
    pelvis_base = hip_z + proportions.torso_length * 0.10
    chest_top = pelvis_base + proportions.torso_length

    add("root", (0.0, 0.0, 0.0), (0.0, 0.0, 0.16), None, deform=False)
    add(
        "pelvis",
        (0.0, 0.0, hip_z - proportions.torso_length * 0.08),
        (0.0, 0.0, pelvis_base),
        "root",
    )

    spine_01_tail = pelvis_base + proportions.torso_length * 0.25
    spine_02_tail = pelvis_base + proportions.torso_length * 0.58
    add("spine_01", (0.0, 0.0, pelvis_base), (0.0, 0.0, spine_01_tail), "pelvis", connected=True)
    add("spine_02", (0.0, 0.0, spine_01_tail), (0.0, 0.0, spine_02_tail), "spine_01", connected=True)
    add("chest", (0.0, 0.0, spine_02_tail), (0.0, 0.0, chest_top), "spine_02", connected=True)
    add("neck", (0.0, 0.0, chest_top), (0.0, 0.0, chest_top + proportions.neck_length), "chest", connected=True)
    add(
        "head",
        (0.0, 0.0, chest_top + proportions.neck_length),
        (0.0, 0.0, chest_top + proportions.neck_length + proportions.head_height * 0.82),
        "neck",
        connected=True,
    )

    arm_down_angle = math.radians(28.0)
    arm_horizontal = math.cos(arm_down_angle)
    arm_drop = math.sin(arm_down_angle)
    upper_length = proportions.arm_length * 0.52
    forearm_length = proportions.arm_length - upper_length
    hand_length = proportions.head_height * 0.78
    palm_length = hand_length * 0.47
    finger_length = hand_length - palm_length

    for suffix, side in ((".L", 1.0), (".R", -1.0)):
        direction = Vector((side * arm_horizontal, 0.0, -arm_drop))
        clavicle_head = Vector((side * proportions.shoulder_width * 0.06, 0.0, chest_top - proportions.torso_length * 0.075))
        shoulder = Vector((side * proportions.shoulder_width * 0.5, 0.0, chest_top - proportions.torso_length * 0.11))
        elbow = shoulder + direction * upper_length
        wrist = elbow + direction * forearm_length
        palm_end = wrist + direction * palm_length

        add(f"clavicle{suffix}", clavicle_head, shoulder, "chest")
        add(f"upper_arm{suffix}", shoulder, elbow, f"clavicle{suffix}", connected=True)
        add(f"forearm{suffix}", elbow, wrist, f"upper_arm{suffix}", connected=True)
        add(f"hand{suffix}", wrist, palm_end, f"forearm{suffix}", connected=True)

        finger_data = (
            ("index", -0.026, 1.00, -0.010),
            ("middle", -0.009, 1.06, -0.003),
            ("ring", 0.009, 0.98, 0.004),
            ("pinky", 0.026, 0.84, 0.012),
        )
        for finger_name, y_offset, length_factor, y_fan in finger_data:
            root = palm_end + Vector((0.0, y_offset, 0.0))
            total = finger_length * length_factor
            segment_lengths = (total * 0.42, total * 0.33, total * 0.25)
            parent = f"hand{suffix}"
            segment_head = root
            for segment_index, segment_length in enumerate(segment_lengths, start=1):
                segment_direction = (direction + Vector((0.0, y_fan, -0.012))).normalized()
                segment_tail = segment_head + segment_direction * segment_length
                bone_name = f"{finger_name}_{segment_index:02d}{suffix}"
                add(
                    bone_name,
                    segment_head,
                    segment_tail,
                    parent,
                    connected=segment_index > 1,
                )
                parent = bone_name
                segment_head = segment_tail

        thumb_root = wrist + direction * (palm_length * 0.30) + Vector((0.0, -0.035, -0.012))
        thumb_direction = (direction * 0.70 + Vector((0.0, -0.62, -0.18))).normalized()
        thumb_mid = thumb_root + thumb_direction * (finger_length * 0.42)
        thumb_tip = thumb_mid + thumb_direction * (finger_length * 0.36)
        add(f"thumb_01{suffix}", thumb_root, thumb_mid, f"hand{suffix}")
        add(f"thumb_02{suffix}", thumb_mid, thumb_tip, f"thumb_01{suffix}", connected=True)

        hip = Vector((side * proportions.pelvis_width * 0.36, 0.0, hip_z))
        knee = Vector((hip.x, 0.012, ankle_z + proportions.leg_length * 0.49))
        ankle = Vector((hip.x, 0.0, ankle_z))
        foot_length = proportions.head_height * 1.05
        toe_length = foot_length * 0.34
        ball = Vector((hip.x, -foot_length * 0.69, ankle_z * 0.42))
        toe = Vector((hip.x, -(foot_length * 0.69 + toe_length), ankle_z * 0.35))

        add(f"thigh{suffix}", hip, knee, "pelvis")
        add(f"shin{suffix}", knee, ankle, f"thigh{suffix}", connected=True)
        add(f"foot{suffix}", ankle, ball, f"shin{suffix}", connected=True)
        add(f"toe{suffix}", ball, toe, f"foot{suffix}", connected=True)

    return specs


def hierarchy_signature(specs: Iterable[BoneSpec]) -> tuple[tuple[str, str | None], ...]:
    return tuple(sorted((spec.name, spec.parent) for spec in specs))


def reset_scene() -> bpy.types.Scene:
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for collection in (
        bpy.data.armatures,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.actions,
        bpy.data.curves,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in list(collection):
            collection.remove(datablock)

    scene = bpy.context.scene
    # Headless regeneration should replace only the named deliverable, not
    # accumulate Blender's numbered .blend1/.blend2 safety copies.
    bpy.context.preferences.filepaths.save_version = 0
    scene.frame_start = NEUTRAL_FRAME
    scene.frame_end = max(POSE_FRAMES.values())
    scene.render.engine = "BLENDER_EEVEE"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    return scene


def create_armature(template: TemplateSpec, specs: Sequence[BoneSpec]) -> bpy.types.Object:
    armature_data = bpy.data.armatures.new(f"{template.rig_name}Skeleton")
    armature = bpy.data.objects.new(template.rig_name, armature_data)
    bpy.context.collection.objects.link(armature)
    armature.show_in_front = True
    armature.data.display_type = "OCTAHEDRAL"
    armature["space_nova_template"] = template.rig_name
    armature["space_nova_generator_version"] = GENERATOR_VERSION
    armature["space_nova_neutral_pose"] = "A-pose"
    armature["space_nova_units"] = "metres"
    armature["space_nova_proportions"] = json.dumps(asdict(template.proportions), sort_keys=True)

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones: dict[str, bpy.types.EditBone] = {}
    for spec in specs:
        bone = armature_data.edit_bones.new(spec.name)
        bone.head = spec.head
        bone.tail = spec.tail
        bone.roll = 0.0
        bone.use_deform = spec.deform
        edit_bones[spec.name] = bone

    for spec in specs:
        bone = edit_bones[spec.name]
        if spec.parent is not None:
            bone.parent = edit_bones[spec.parent]
            bone.use_connect = spec.connected

    bpy.ops.object.mode_set(mode="OBJECT")
    return armature


def _tube_radius(name: str, proportions: HumanoidProportions) -> float:
    if name == "pelvis":
        return proportions.pelvis_width * 0.23
    if name == "chest":
        return proportions.shoulder_width * 0.20
    if name.startswith("spine_"):
        return proportions.pelvis_width * 0.18
    if name == "neck":
        return proportions.head_width * 0.25
    if name.startswith("clavicle"):
        return proportions.head_width * 0.16
    if name.startswith("upper_arm"):
        return proportions.head_width * 0.27
    if name.startswith("forearm"):
        return proportions.head_width * 0.22
    if name.startswith("hand"):
        return proportions.head_width * 0.20
    if any(name.startswith(prefix) for prefix in ("thumb", "index", "middle", "ring", "pinky")):
        return max(0.007, proportions.head_width * 0.055)
    if name.startswith("thigh"):
        return proportions.pelvis_width * 0.20
    if name.startswith("shin"):
        return proportions.pelvis_width * 0.15
    if name.startswith("foot"):
        return proportions.head_width * 0.24
    if name.startswith("toe"):
        return proportions.head_width * 0.19
    return proportions.head_width * 0.18


def _append_tube(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    skin_weights: list[dict[str, float]],
    spec: BoneSpec,
    radius: float,
    sides: int = 8,
) -> None:
    head = Vector(spec.head)
    tail = Vector(spec.tail)
    axis = (tail - head).normalized()
    helper = Vector((0.0, 0.0, 1.0)) if abs(axis.z) < 0.90 else Vector((0.0, 1.0, 0.0))
    basis_u = axis.cross(helper).normalized()
    basis_v = axis.cross(basis_u).normalized()
    start_index = len(vertices)
    rings = ((0.04, radius * 0.68), (0.50, radius), (0.96, radius * 0.68))

    for ring_index, (position, ring_radius) in enumerate(rings):
        center = head.lerp(tail, position)
        vertex_weights = {spec.name: 1.0}
        if ring_index == 0 and spec.parent not in (None, "root"):
            # A small generated blend zone exercises actual joint skinning
            # rather than treating every diagnostic segment as a rigid prop.
            vertex_weights = {spec.name: 0.72, spec.parent: 0.28}
        for side in range(sides):
            angle = math.tau * side / sides
            point = center + basis_u * math.cos(angle) * ring_radius + basis_v * math.sin(angle) * ring_radius
            vertices.append(_v(point))
            skin_weights.append(vertex_weights)

    for ring in range(len(rings) - 1):
        current = start_index + ring * sides
        following = current + sides
        for side in range(sides):
            next_side = (side + 1) % sides
            faces.append((current + side, current + next_side, following + next_side, following + side))

    faces.append(tuple(start_index + side for side in reversed(range(sides))))
    last_ring = start_index + (len(rings) - 1) * sides
    faces.append(tuple(last_ring + side for side in range(sides)))


def _append_head(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    skin_weights: list[dict[str, float]],
    spec: BoneSpec,
    proportions: HumanoidProportions,
) -> None:
    center = Vector(spec.head) + Vector((0.0, 0.0, proportions.head_height * 0.47))
    radius_x = proportions.head_width * 0.5
    radius_y = proportions.head_depth * 0.5
    radius_z = proportions.head_height * 0.5
    sides = 10
    latitude_rings = 6
    start_index = len(vertices)

    vertices.append(_v(center + Vector((0.0, 0.0, radius_z))))
    skin_weights.append({spec.name: 1.0})
    top_index = start_index

    for ring in range(1, latitude_rings):
        phi = math.pi * ring / latitude_rings
        vertex_weights = (
            {spec.name: 0.72, "neck": 0.28}
            if ring == latitude_rings - 1
            else {spec.name: 1.0}
        )
        for side in range(sides):
            theta = math.tau * side / sides
            point = center + Vector(
                (
                    radius_x * math.sin(phi) * math.cos(theta),
                    radius_y * math.sin(phi) * math.sin(theta),
                    radius_z * math.cos(phi),
                )
            )
            vertices.append(_v(point))
            skin_weights.append(vertex_weights)

    bottom_index = len(vertices)
    vertices.append(_v(center - Vector((0.0, 0.0, radius_z))))
    skin_weights.append({spec.name: 0.72, "neck": 0.28})

    first_ring = start_index + 1
    for side in range(sides):
        next_side = (side + 1) % sides
        faces.append((top_index, first_ring + side, first_ring + next_side))

    for ring in range(latitude_rings - 2):
        current = first_ring + ring * sides
        following = current + sides
        for side in range(sides):
            next_side = (side + 1) % sides
            faces.append((current + side, following + side, following + next_side, current + next_side))

    last_ring = first_ring + (latitude_rings - 2) * sides
    for side in range(sides):
        next_side = (side + 1) % sides
        faces.append((last_ring + side, bottom_index, last_ring + next_side))


def create_test_mesh(
    template: TemplateSpec,
    armature: bpy.types.Object,
    specs: Sequence[BoneSpec],
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    skin_weights: list[dict[str, float]] = []

    for spec in specs:
        if not spec.deform:
            continue
        if spec.name == "head":
            _append_head(vertices, faces, skin_weights, spec, template.proportions)
        else:
            _append_tube(vertices, faces, skin_weights, spec, _tube_radius(spec.name, template.proportions))

    mesh_data = bpy.data.meshes.new(f"{template.mesh_name}Geometry")
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update(calc_edges=True)
    mesh = bpy.data.objects.new(template.mesh_name, mesh_data)
    bpy.context.collection.objects.link(mesh)
    mesh["space_nova_test_mesh"] = True
    mesh["space_nova_binding"] = "deterministic generated blended skin weights"

    material = bpy.data.materials.new(f"{template.rig_name}TestMaterial")
    material.diffuse_color = template.color
    material.metallic = 0.05
    material.roughness = 0.62
    mesh_data.materials.append(material)

    groups: dict[str, bpy.types.VertexGroup] = {}
    for spec in specs:
        if not spec.deform:
            continue
        groups[spec.name] = mesh.vertex_groups.new(name=spec.name)

    weighted_indices: dict[tuple[str, float], list[int]] = {}
    for vertex_index, vertex_weights in enumerate(skin_weights):
        for bone_name, weight in vertex_weights.items():
            weighted_indices.setdefault((bone_name, weight), []).append(vertex_index)

    for (bone_name, weight), vertex_indices in weighted_indices.items():
        groups[bone_name].add(vertex_indices, weight, "REPLACE")

    modifier = mesh.modifiers.new(name="SpaceNovaArmature", type="ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    mesh.parent = armature
    mesh.matrix_parent_inverse = armature.matrix_world.inverted()

    for polygon in mesh_data.polygons:
        polygon.use_smooth = True

    return mesh


def create_pose_tests(armature: bpy.types.Object) -> bpy.types.Action:
    action = bpy.data.actions.new(name="SpaceNovaPoseTests")
    action.use_fake_user = True
    armature.animation_data_create()
    armature.animation_data.action = action

    frames = [NEUTRAL_FRAME, *POSE_FRAMES.values()]
    for frame in frames:
        for pose_bone in armature.pose.bones:
            pose_bone.rotation_mode = "XYZ"
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.rotation_euler = (0.0, 0.0, 0.0)

        if frame == POSE_FRAMES["shoulder_rotation"]:
            armature.pose.bones["upper_arm.L"].rotation_euler.x = math.radians(34.0)
            armature.pose.bones["upper_arm.R"].rotation_euler.x = math.radians(-34.0)
        elif frame == POSE_FRAMES["elbow_bending"]:
            armature.pose.bones["forearm.L"].rotation_euler.x = math.radians(72.0)
            armature.pose.bones["forearm.R"].rotation_euler.x = math.radians(-72.0)
        elif frame == POSE_FRAMES["knee_bending"]:
            armature.pose.bones["thigh.L"].rotation_euler.x = math.radians(-14.0)
            armature.pose.bones["thigh.R"].rotation_euler.x = math.radians(-14.0)
            armature.pose.bones["shin.L"].rotation_euler.x = math.radians(68.0)
            armature.pose.bones["shin.R"].rotation_euler.x = math.radians(68.0)
        elif frame == POSE_FRAMES["hip_movement"]:
            armature.pose.bones["pelvis"].location.x = 0.10
            armature.pose.bones["pelvis"].rotation_euler.z = math.radians(12.0)
        elif frame == POSE_FRAMES["head_turning"]:
            # A vertical bone's local Y axis is its anatomical yaw axis.
            armature.pose.bones["head"].rotation_euler.y = math.radians(42.0)

        for pose_bone in armature.pose.bones:
            pose_bone.keyframe_insert(data_path="location", frame=frame, group=pose_bone.name)
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=pose_bone.name)

    for name, frame in POSE_FRAMES.items():
        armature.id_data.animation_data.action.pose_markers.new(name).frame = frame

    for fcurve in action.fcurves:
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = "BEZIER"

    bpy.context.scene.frame_set(NEUTRAL_FRAME)
    return action


def create_template(template: TemplateSpec) -> tuple[bpy.types.Object, bpy.types.Object]:
    template.proportions.validate()
    scene = reset_scene()
    scene.name = f"{template.rig_name}Scene"
    specs = build_bone_specs(template.proportions)
    armature = create_armature(template, specs)
    mesh = create_test_mesh(template, armature, specs)
    create_pose_tests(armature)

    scene["space_nova_template"] = template.rig_name
    scene["space_nova_generator_version"] = GENERATOR_VERSION
    scene["space_nova_bone_count"] = len(specs)
    scene["space_nova_pose_test_frames"] = json.dumps(POSE_FRAMES, sort_keys=True)
    return armature, mesh


def export_template(template: TemplateSpec, output_dir: str | Path) -> dict[str, Path]:
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    armature, mesh = create_template(template)

    blend_path = output_path / f"{template.rig_name}.blend"
    glb_path = output_path / f"{template.rig_name}.glb"

    bpy.context.view_layer.objects.active = armature
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
    return {"blend": blend_path, "glb": glb_path}


def template_with_overrides(key: str, overrides: Mapping[str, float]) -> TemplateSpec:
    template = TEMPLATES[key]
    if not overrides:
        return template
    return replace(template, proportions=template.proportions.with_overrides(overrides))

