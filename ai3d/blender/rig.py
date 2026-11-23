"""Mixamo-compatible humanoid rig with automatic weights (run inside Blender).

blender --background --factory-startup --python-exit-code 1 \
  --python ai3d/blender/rig.py -- --input 06_game.glb --output 07_rigged.glb

* Finds the character's joints from the mesh itself (crotch, arm tips,
  limb cross-section centres) instead of fixed percentages only.
* Turns the character to face -Y (glTF/Three.js forward) if needed, using
  the direction the toes point.
* Builds Mixamo bone names ("mixamorig:Hips" ... ) so Mixamo animations
  retarget by name in Three.js (three strips the colon: mixamorigHips).
* Blender automatic (heat) weights; any vertex heat misses gets the
  nearest bone. Max 4 influences, normalised, as glTF expects.
* Optional short test action (arms up/down, knee bends, head turn) so you
  can scrub deformation in Blender or a Three.js viewer.
Writes the rigged GLB, an editable .blend next to it, and stats JSON.
"""
import argparse
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Matrix, Quaternion, Vector  # noqa: E402

from common import (  # noqa: E402
    export_glb, import_glb, join_meshes, reset_scene, script_args, select_only, write_json,
)

SIDES = (("Left", 1.0), ("Right", -1.0))


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--prefix", default="mixamorig:")
    p.add_argument("--no-test-animation", action="store_true")
    p.add_argument("--stats", type=Path)
    a = p.parse_args(script_args())
    if a.input.resolve() == a.output.resolve():
        p.error("output must differ from input")
    return a


# ---------------------------------------------------------------- geometry

def world_points(obj):
    mw = obj.matrix_world
    return [mw @ v.co for v in obj.data.vertices]


def centre(points, fallback):
    if not points:
        return fallback.copy()
    total = Vector((0.0, 0.0, 0.0))
    for p in points:
        total += p
    return total / len(points)


def runs(values, gap):
    """Group sorted 1-D values into contiguous runs separated by > gap."""
    values = sorted(values)
    groups, current = [], []
    for v in values:
        if current and v - current[-1] > gap:
            groups.append(current)
            current = []
        current.append(v)
    if current:
        groups.append(current)
    return groups


def slab(points, z, half):
    return [p for p in points if abs(p.z - z) <= half]


def torso_half_width(points, z, H):
    xs = [p.x for p in slab(points, z, 0.01 * H)]
    for group in runs(xs, 0.012 * H):
        if group[0] <= 0.0 <= group[-1]:
            return max(abs(group[0]), abs(group[-1]))
    return 0.11 * H


def facing_sign(points, zmin, H):
    """-1 if toes point to -Y (already facing -Y), +1 if to +Y, 0 unknown."""
    feet = [p for p in points if p.z < zmin + 0.035 * H]
    shins = [p for p in points if zmin + 0.12 * H < p.z < zmin + 0.22 * H]
    if not feet or not shins:
        return 0
    diff = centre(feet, Vector()).y - centre(shins, Vector()).y
    if abs(diff) < 0.006 * H:
        return 0
    return 1 if diff > 0 else -1


def find_crotch(points, zmin, H):
    """Lowest height where the middle of the body is solid (legs have merged).

    Human crotch height is ~0.44-0.50 of standing height; the search is
    clamped to 0.42-0.52 so touching thighs cannot pull it down to the knees.
    """
    z = zmin + 0.42 * H
    while z < zmin + 0.52 * H:
        if any(abs(p.x) < 0.006 * H for p in slab(points, z, 0.004 * H)):
            return z
        z += 0.004 * H
    return zmin + 0.47 * H


def limb_centre(points, origin, direction, distance, half):
    """Centre of the limb cross-section `distance` along `direction`."""
    sel = [p for p in points if abs((p - origin).dot(direction) - distance) <= half]
    return centre(sel, origin + direction * distance)


def landmarks(obj):
    pts = world_points(obj)
    zmin = min(p.z for p in pts)
    zmax = max(p.z for p in pts)
    H = zmax - zmin
    lm = {"_height": H, "_zmin": zmin}

    crotch = find_crotch(pts, zmin, H)
    hip_z = crotch + 0.035 * H
    torso_y = centre([p for p in slab(pts, hip_z + 0.1 * H, 0.02 * H) if abs(p.x) < 0.08 * H],
                     Vector((0, 0, 0))).y

    # Shoulders: torso width at chest height, arm points outside it.
    chest_z = zmin + 0.72 * H
    chest_half = torso_half_width(pts, chest_z, H)
    shoulder_guess_z = zmin + 0.815 * H
    lm["Hips"] = Vector((0.0, torso_y, hip_z + 0.01 * H))
    lm["Spine"] = Vector((0.0, torso_y, hip_z + 0.07 * H))
    lm["Spine1"] = Vector((0.0, torso_y, hip_z + 0.14 * H))
    lm["Spine2"] = Vector((0.0, torso_y, hip_z + 0.21 * H))

    shoulder_zs = []
    for side, s in SIDES:
        arm = [p for p in pts if s * p.x > chest_half * 1.05 and p.z > zmin + 0.38 * H]
        root_guess = Vector((s * chest_half, torso_y, shoulder_guess_z))
        if len(arm) < 10:
            tip = root_guess + Vector((s * 0.35 * H, 0, -0.25 * H))
            root = root_guess
        else:
            tip = max(arm, key=lambda p: (p - root_guess).length)
            near = [p for p in arm if s * p.x < chest_half + 0.05 * H]
            root = centre(near, root_guess)
            root.x = s * chest_half * 0.92
        length = (tip - root).length
        d = (tip - root).normalized()
        sample = [p for p in arm] or pts
        elbow = limb_centre(sample, root, d, length * 0.45, 0.02 * H)
        wrist = limb_centre(sample, root, d, length * 0.80, 0.015 * H)
        lm[f"{side}Arm"] = root
        lm[f"{side}ForeArm"] = elbow
        lm[f"{side}Hand"] = wrist
        lm[f"{side}HandEnd"] = tip
        lm[f"{side}Shoulder"] = Vector((s * 0.025 * H, torso_y, root.z))
        shoulder_zs.append(root.z)

    sh_z = sum(shoulder_zs) / len(shoulder_zs)
    lm["Neck"] = Vector((0.0, torso_y, sh_z + 0.02 * H))
    # Mixamo-like spacing of the three spine joints between hips and neck.
    span = lm["Neck"].z - lm["Hips"].z
    for name, frac in (("Spine", 0.22), ("Spine1", 0.44), ("Spine2", 0.66)):
        z = lm["Hips"].z + span * frac
        sl = [p for p in slab(pts, z, 0.015 * H) if abs(p.x) < 0.06 * H]
        lm[name] = Vector((0.0, centre(sl, lm["Hips"]).y, z))
    head_pts = [p for p in pts if p.z > sh_z + 0.07 * H and abs(p.x) < 0.1 * H]
    head_y = centre(head_pts, lm["Neck"]).y
    lm["Head"] = Vector((0.0, head_y, sh_z + 0.075 * H))
    lm["HeadTop_End"] = Vector((0.0, head_y, zmax))

    for side, s in SIDES:
        leg = [p for p in pts if s * p.x > 0.0 and p.z < crotch]
        hip_slice = [p for p in leg if p.z > crotch - 0.05 * H]
        hip = centre(hip_slice, Vector((s * 0.06 * H, torso_y, hip_z)))
        hip.z = hip_z
        knee_z = zmin + (hip_z - zmin) * 0.52
        knee = centre(slab(leg, knee_z, 0.012 * H), Vector((hip.x, torso_y, knee_z)))
        ankle_z = zmin + 0.055 * H
        ankle_pts = [p for p in slab(leg, ankle_z, 0.01 * H)]
        ankle = centre(ankle_pts, Vector((knee.x, knee.y, ankle_z)))
        # Behind-most part of the slice is the ankle, the rest is the foot.
        if ankle_pts:
            ys = sorted(p.y for p in ankle_pts)
            ankle.y = ys[len(ys) * 3 // 4]
        foot = [p for p in leg if p.z < zmin + 0.05 * H]
        toe = min(foot, key=lambda p: p.y) if foot else ankle + Vector((0, -0.08 * H, 0))
        toe_end = Vector((ankle.x, toe.y, zmin + 0.012 * H))
        toe_base = ankle.lerp(toe_end, 0.62)
        toe_base.z = zmin + 0.02 * H
        lm[f"{side}UpLeg"] = hip
        lm[f"{side}Leg"] = knee
        lm[f"{side}Foot"] = ankle
        lm[f"{side}ToeBase"] = toe_base
        lm[f"{side}Toe_End"] = toe_end
    return lm


# ---------------------------------------------------------------- skeleton

def bone_specs():
    """(name, head landmark, tail landmark, parent, deform)."""
    specs = [
        ("Hips", "Hips", "Spine", None, True),
        ("Spine", "Spine", "Spine1", "Hips", True),
        ("Spine1", "Spine1", "Spine2", "Spine", True),
        ("Spine2", "Spine2", "Neck", "Spine1", True),
        ("Neck", "Neck", "Head", "Spine2", True),
        ("Head", "Head", "HeadTop_End", "Neck", True),
    ]
    for side, _s in SIDES:
        specs += [
            (f"{side}Shoulder", f"{side}Shoulder", f"{side}Arm", "Spine2", True),
            (f"{side}Arm", f"{side}Arm", f"{side}ForeArm", f"{side}Shoulder", True),
            (f"{side}ForeArm", f"{side}ForeArm", f"{side}Hand", f"{side}Arm", True),
            (f"{side}Hand", f"{side}Hand", f"{side}HandEnd", f"{side}ForeArm", True),
            (f"{side}UpLeg", f"{side}UpLeg", f"{side}Leg", "Hips", True),
            (f"{side}Leg", f"{side}Leg", f"{side}Foot", f"{side}UpLeg", True),
            (f"{side}Foot", f"{side}Foot", f"{side}ToeBase", f"{side}Leg", True),
            (f"{side}ToeBase", f"{side}ToeBase", f"{side}Toe_End", f"{side}Foot", True),
        ]
    return specs


def build_armature(lm, prefix):
    H = lm["_height"]
    data = bpy.data.armatures.new("AI3D_Armature")
    arm = bpy.data.objects.new("Armature", data)
    bpy.context.collection.objects.link(arm)
    select_only([arm])
    bpy.ops.object.mode_set(mode="EDIT")
    bones = {}
    for name, head, tail, parent, deform in bone_specs():
        b = data.edit_bones.new(prefix + name)
        b.head = lm[head]
        b.tail = lm[tail]
        if (b.tail - b.head).length < 0.01 * H:
            b.tail = b.head + Vector((0, 0, 0.03 * H))
        b.use_deform = deform
        if parent:
            b.parent = bones[parent]
            b.use_connect = (bones[parent].tail - b.head).length < 1e-4
        bones[name] = b
    leaf = data.edit_bones.new(prefix + "HeadTop_End")
    leaf.head = lm["HeadTop_End"]
    leaf.tail = lm["HeadTop_End"] + Vector((0, 0, 0.04 * H))
    leaf.parent = bones["Head"]
    leaf.use_deform = False
    for side, _s in SIDES:
        end = data.edit_bones.new(prefix + f"{side}Toe_End")
        end.head = lm[f"{side}Toe_End"]
        end.tail = end.head + Vector((0, -0.03 * H, 0))
        end.parent = bones[f"{side}ToeBase"]
        end.use_deform = False
    for b in data.edit_bones:
        direction = (b.tail - b.head).normalized()
        up = Vector((0, 0, 1)) if abs(direction.y) > 0.7 else Vector((0, -1, 0))
        b.align_roll(up)
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


# ---------------------------------------------------------------- weights

def segment_distance(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def weight_report(mesh_obj, deform_names):
    groups = {g.index: g.name for g in mesh_obj.vertex_groups}
    unweighted, max_inf = 0, 0
    used = set()
    for v in mesh_obj.data.vertices:
        ws = [(groups[g.group], g.weight) for g in v.groups
              if g.weight > 1e-4 and groups.get(g.group) in deform_names]
        if not ws:
            unweighted += 1
        max_inf = max(max_inf, len(ws))
        used.update(n for n, _ in ws)
    return unweighted, max_inf, sorted(set(deform_names) - used)


def weld(obj):
    """Join vertices glTF split at UV seams and drop degenerate faces.

    Heat weighting fails outright ("failed to find solution") on a mesh cut
    into islands along its UV seams. Blender keeps UVs per face corner, so
    welding does not damage the texture layout.
    """
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-4)
    bpy.ops.mesh.dissolve_degenerate(threshold=1e-4)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def heat(mesh_obj, arm):
    select_only([mesh_obj, arm], active=arm)
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")


def heat_via_proxy(body, arm, deform_names, height):
    """Heat-weight a voxel-remeshed copy, then copy weights to the real mesh."""
    from mathutils.kdtree import KDTree
    proxy = body.copy()
    proxy.data = body.data.copy()
    bpy.context.collection.objects.link(proxy)
    proxy.parent = None
    proxy.modifiers.clear()
    proxy.vertex_groups.clear()
    select_only([proxy])
    proxy.data.remesh_voxel_size = 0.006 * height
    bpy.ops.object.voxel_remesh()
    weld(proxy)
    heat(proxy, arm)
    tree = KDTree(len(proxy.data.vertices))
    for v in proxy.data.vertices:
        tree.insert(proxy.matrix_world @ v.co, v.index)
    tree.balance()
    names = {g.index: g.name for g in proxy.vertex_groups}
    source = [[(names[g.group], g.weight) for g in v.groups if names.get(g.group) in deform_names]
              for v in proxy.data.vertices]
    for g in list(body.vertex_groups):
        body.vertex_groups.remove(g)
    mw = body.matrix_world
    for v in body.data.vertices:
        total = {}
        for _co, idx, dist in tree.find_n(mw @ v.co, 3):
            w = 1.0 / (dist + 1e-4)
            for name, weight in source[idx]:
                total[name] = total.get(name, 0.0) + weight * w
        for name, weight in total.items():
            group = body.vertex_groups.get(name) or body.vertex_groups.new(name=name)
            group.add([v.index], weight, "REPLACE")
    bpy.data.objects.remove(proxy, do_unlink=True)


def fill_unweighted(mesh_obj, arm, deform_names):
    """Last resort for vertices with no weight: blend the two nearest bones."""
    groups = {g.index: g.name for g in mesh_obj.vertex_groups}
    segments = []
    for bone in arm.data.bones:
        if bone.name in deform_names:
            segments.append((bone.name, arm.matrix_world @ bone.head_local,
                             arm.matrix_world @ bone.tail_local))
    fixed = 0
    mw = mesh_obj.matrix_world
    for v in mesh_obj.data.vertices:
        if any(g.weight > 1e-4 and groups.get(g.group) in deform_names for g in v.groups):
            continue
        p = mw @ v.co
        near = sorted((segment_distance(p, s[1], s[2]), s[0]) for s in segments)[:2]
        inv = [(1.0 / (d + 1e-4) ** 4, name) for d, name in near]
        total = sum(w for w, _ in inv)
        for w, name in inv:
            group = mesh_obj.vertex_groups.get(name) or mesh_obj.vertex_groups.new(name=name)
            group.add([v.index], w / total, "REPLACE")
        fixed += 1
    return fixed


# ---------------------------------------------------------------- test action

def world_rotation_to_local(pbone, axis, degrees):
    rest = pbone.bone.matrix_local.to_3x3()
    q = Quaternion(axis, math.radians(degrees)).to_matrix()
    return (rest.inverted() @ q @ rest).to_quaternion()


def add_test_action(arm, prefix):
    select_only([arm])
    bpy.ops.object.mode_set(mode="POSE")
    action = bpy.data.actions.new("ai3d_pose_test")
    arm.animation_data_create()
    arm.animation_data.action = action
    pb = arm.pose.bones
    keys = {
        1: {},
        20: {"LeftArm": ((0, 1, 0), -50), "RightArm": ((0, 1, 0), 50)},
        40: {"LeftArm": ((0, 1, 0), 45), "RightArm": ((0, 1, 0), -45),
             "LeftForeArm": ((0, 0, 1), 30), "RightForeArm": ((0, 0, 1), -30)},
        60: {"LeftUpLeg": ((1, 0, 0), -45), "LeftLeg": ((1, 0, 0), 70),
             "Spine1": ((0, 0, 1), 15), "Head": ((0, 0, 1), 30)},
        80: {"RightUpLeg": ((1, 0, 0), -45), "RightLeg": ((1, 0, 0), 70),
             "Spine1": ((0, 0, 1), -15), "Head": ((1, 0, 0), 15)},
        100: {},
    }
    for frame, pose in keys.items():
        for bone in pb:
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Quaternion()
        for name, (axis, deg) in pose.items():
            bone = pb.get(prefix + name)
            if bone:
                bone.rotation_quaternion = world_rotation_to_local(bone, Vector(axis), deg)
        for bone in pb:
            bone.keyframe_insert("rotation_quaternion", frame=frame)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 100
    for bone in pb:
        bone.rotation_quaternion = Quaternion()
    bpy.ops.object.mode_set(mode="OBJECT")
    return action.name


# ---------------------------------------------------------------- main

def main():
    a = parse()
    reset_scene()
    imported = import_glb(a.input)
    for obj in imported:
        if obj.type == "ARMATURE":
            raise SystemExit("Input already has an armature; give the unrigged 06_game.glb")
    body = join_meshes(imported, "AI3D_Character")
    pts = world_points(body)
    zmin = min(p.z for p in pts)
    H = max(p.z for p in pts) - zmin

    sign = facing_sign(pts, zmin, H)
    turned = False
    if sign > 0:
        body.matrix_world = Matrix.Rotation(math.pi, 4, "Z") @ body.matrix_world
        select_only([body])
        bpy.ops.object.transform_apply(rotation=True)
        turned = True
    # Centre on X/Y, feet on the floor.
    pts = world_points(body)
    cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
    cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
    body.location -= Vector((cx, cy, min(p.z for p in pts)))
    select_only([body])
    bpy.ops.object.transform_apply(location=True)

    weld(body)
    lm = landmarks(body)
    arm = build_armature(lm, a.prefix)
    deform = {b.name for b in arm.data.bones if b.use_deform}

    method = "heat"
    try:
        heat(body, arm)
    except RuntimeError as exc:
        print("[rig] automatic weights failed:", exc, flush=True)
        select_only([body, arm], active=arm)
        bpy.ops.object.parent_set(type="ARMATURE_NAME")
    missed, _, _ = weight_report(body, deform)
    if missed / max(1, len(body.data.vertices)) > 0.05:
        print(f"[rig] heat weights missed {missed} vertices; retrying on a voxel proxy", flush=True)
        heat_via_proxy(body, arm, deform, lm["_height"])
        method = "heat (voxel proxy)"
    unweighted_heat, _, _ = weight_report(body, deform)
    filled = fill_unweighted(body, arm, deform)

    select_only([body])
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    unweighted, max_inf, unused = weight_report(body, deform)

    action = None
    if not a.no_test_animation:
        action = add_test_action(arm, a.prefix)

    export_glb(a.output, [body, arm], animations=action is not None, apply_modifiers=False)
    blend = a.output.with_suffix(".blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    total = len(body.data.vertices)
    stats = {
        "bones": len(arm.data.bones),
        "deform_bones": len(deform),
        "bone_prefix": a.prefix,
        "turned_to_face_minus_y": turned,
        "facing_detected": {1: "+Y", -1: "-Y", 0: "unknown (assumed -Y)"}[sign],
        "weight_method": method,
        "vertices": total,
        "unweighted_after_heat_fraction": round(unweighted_heat / max(1, total), 4),
        "nearest_bone_filled": filled,
        "unweighted_final": unweighted,
        "max_influences": max_inf,
        "deform_bones_without_vertices": unused,
        "test_action": action,
        "height_m": round(H, 4),
        "blend": str(blend),
    }
    print("[rig]", stats, flush=True)
    if a.stats:
        write_json(a.stats, stats)


if __name__ == "__main__":
    main()
