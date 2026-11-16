#!/usr/bin/env python3
"""Mara: editable 3D *proxy* volumes from approved 2D seam landmarks.

This is a geometric fitting experiment, NOT a generated character, not a
validated anatomical reconstruction, and not a source of approved 3D depth.
It creates ten independent Blender mesh objects with shared joint centers.
The body shapes, depths, radii and foot extension are explicitly assumed.

From ai3d root:
  python3 tools/mara_depth_proxy.py --audit-only
  blender --background --factory-startup --python-exit-code 1 \
    --python tools/mara_depth_proxy.py -- \
    --output outputs/mara_depth_proxy_v1

Requires tools/mara_attachment_scaffold.py and
outputs/mara_reference_refine_v1/reference_parts.json. No external AI calls.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from mara_attachment_scaffold import (  # noqa: E402
    DEFAULT_MASTER, DEFAULT_MANIFEST, EXPECTED_PARTS,
    audit, to_world,
)

DEFAULT_OUTPUT = Path("outputs/mara_depth_proxy_v1")
# Dimensions below are assumptions, NOT measurements from the single image.
# Radius entries are in METERS, and refer to ellipse half-axes.
SIZES = {
    "neck": (0.055, 0.055),
    "shoulder": (0.068, 0.068),
    "elbow": (0.052, 0.048),
    "wrist": (0.031, 0.030),
    "palm": (0.048, 0.030),
    "hip": (0.087, 0.092),
    "knee": (0.057, 0.056),
    "ankle": (0.037, 0.042),
}
MATERIALS = {
    "torso_pelvis": (0.87, 0.59, 0.23),
    "head": (0.26, 0.70, 0.39),
    "left_arm": (0.31, 0.58, 0.91),
    "right_arm": (0.31, 0.58, 0.91),
    "left_hand": (0.85, 0.40, 0.36),
    "right_hand": (0.85, 0.40, 0.36),
    "left_leg": (0.62, 0.42, 0.82),
    "right_leg": (0.62, 0.42, 0.82),
    "left_foot": (0.92, 0.48, 0.28),
    "right_foot": (0.92, 0.48, 0.28),
}


def anchored(parts: dict, part_id: str, anchor: str) -> tuple[float, float, float]:
    return to_world(tuple(parts[part_id]["anchors_master_xy"][anchor]))


def between(a, b, t: float):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


def plus(a, x=0.0, y=0.0, z=0.0):
    return (a[0] + x, a[1] + y, a[2] + z)


def ring(center, ru, rv):
    if ru <= 0 or rv <= 0:
        raise ValueError("All ellipse radii must be positive")
    return {"center_m": list(center), "radius_u_m": ru, "radius_v_m": rv}


def make_profiles(parts: dict) -> dict:
    """Assumed 3D profiles (no 3D geometry dependencies, testable with CPython)."""
    profiles = {}
    neck = anchored(parts, "torso_pelvis", "neck")
    pelvis = anchored(parts, "torso_pelvis", "pelvis_center")
    shoulder_mid = between(anchored(parts, "torso_pelvis", "right_shoulder"),
                           anchored(parts, "torso_pelvis", "left_shoulder"), 0.5)
    torso_sections = [
        ring(neck, *SIZES["neck"]),
        ring(shoulder_mid, 0.195, 0.110),
        ring(between(shoulder_mid, pelvis, 0.38), 0.152, 0.116),
        ring(between(shoulder_mid, pelvis, 0.62), 0.134, 0.098),
        ring(between(shoulder_mid, pelvis, 0.85), 0.165, 0.114),
        ring(pelvis, 0.155, 0.103),
    ]
    profiles["torso_pelvis"] = {"axis_hint": "vertical", "rings": torso_sections}

    crown = anchored(parts, "head", "crown")
    chin = anchored(parts, "head", "chin")
    profiles["head"] = {
        "axis_hint": "vertical",
        "rings": [
            ring(neck, *SIZES["neck"]),
            ring(plus(chin, z=-0.017), 0.081, 0.075),
            ring(between(chin, crown, 0.42), 0.094, 0.087),
            ring(between(chin, crown, 0.75), 0.091, 0.090),
            ring(plus(crown, z=-0.008), 0.041, 0.045),
        ],
    }

    for side in ("left", "right"):
        arm = f"{side}_arm"
        hand = f"{side}_hand"
        leg = f"{side}_leg"
        foot = f"{side}_foot"

        shoulder = anchored(parts, arm, "shoulder")
        elbow = anchored(parts, arm, "elbow")
        wrist = anchored(parts, arm, "wrist")
        palm = anchored(parts, hand, "palm")
        fingers = anchored(parts, hand, "fingertip_region")
        profiles[arm] = {
            "axis_hint": "horizontal",
            "rings": [ring(shoulder, *SIZES["shoulder"]),
                      ring(between(shoulder, elbow, 0.6), 0.059, 0.060),
                      ring(elbow, *SIZES["elbow"]),
                      ring(wrist, *SIZES["wrist"])],
        }
        profiles[hand] = {
            "axis_hint": "horizontal",
            "rings": [ring(wrist, *SIZES["wrist"]),
                      ring(palm, *SIZES["palm"]),
                      ring(between(palm, fingers, 0.82), 0.038, 0.026),
                      ring(fingers, 0.008, 0.010)],
        }

        hip = anchored(parts, leg, "hip")
        knee = anchored(parts, leg, "knee")
        ankle = anchored(parts, leg, "ankle")
        profiles[leg] = {
            "axis_hint": "vertical",
            "rings": [ring(hip, *SIZES["hip"]),
                      ring(between(hip, knee, 0.40), 0.073, 0.078),
                      ring(knee, *SIZES["knee"]),
                      ring(between(knee, ankle, 0.5), 0.050, 0.055),
                      ring(ankle, *SIZES["ankle"])],
        }
        # By design: foot toe direction is a guessed -Y extension (front of character).
        # The front-only master cannot constrain foot length or dorsiflexion.
        toe = anchored(parts, foot, "toe_region")
        profiles[foot] = {
            "axis_hint": "foot",
            "rings": [ring(ankle, *SIZES["ankle"]),
                      ring(plus(ankle, y=-0.055, z=-0.014), 0.055, 0.040),
                      ring(plus(toe, y=-0.155, z=0.022), 0.064, 0.035),
                      ring(plus(toe, y=-0.205, z=0.027), 0.043, 0.026)],
        }

    if set(profiles) != set(EXPECTED_PARTS):
        raise ValueError("Proxy profile does not include exactly ten intended parts")
    for part_id, data in profiles.items():
        if len(data["rings"]) < 2:
            raise ValueError(f"Too few cross-sections: {part_id}")
        for sec in data["rings"]:
            if not all(math.isfinite(v) for v in sec["center_m"]):
                raise ValueError(f"Non-finite center in {part_id}")
    return profiles


def validate_seam_centers(profiles: dict, report: dict) -> list[dict]:
    seam_map = {
        "neck": ("head", 0, "torso_pelvis", 0),
        "left_shoulder": ("left_arm", 0),
        "right_shoulder": ("right_arm", 0),
        "left_wrist": ("left_hand", 0, "left_arm", -1),
        "right_wrist": ("right_hand", 0, "right_arm", -1),
        "left_hip": ("left_leg", 0),
        "right_hip": ("right_leg", 0),
        "left_ankle": ("left_foot", 0, "left_leg", -1),
        "right_ankle": ("right_foot", 0, "right_leg", -1),
    }
    seam_checks = []
    for item in report["seams"]:
        a, ak, b, bk = item["pair"]
        seam_name = ("neck" if ak == "neck_joint" else
                     f"{a.split('_')[0]}_{ak}" if ak in ("shoulder", "wrist", "hip", "ankle") else
                     f"{a}_{ak}")
        if seam_name not in seam_map:
            raise ValueError(f"Unexpected seam {item['pair']}")
        ref = tuple(item["guide_world_m"])
        specs = seam_map[seam_name]
        checks = []
        for i in range(0, len(specs), 2):
            pid, idx = specs[i], specs[i + 1]
            center = profiles[pid]["rings"][idx]["center_m"]
            err = math.dist(ref, center)
            if err > 1e-6:
                raise ValueError(f"3D seam center mismatch: {seam_name}, {pid}: {err}")
            checks.append({"part": pid, "center_error_m": round(err, 8)})
        # Radii also align for pairs of cap sections; torso shoulders/hips need
        # independent socket/cutout topology in a later stage.
        if len(specs) == 4:
            p1, ix1, p2, ix2 = specs
            a1 = profiles[p1]["rings"][ix1]
            a2 = profiles[p2]["rings"][ix2]
            if abs(a1["radius_u_m"] - a2["radius_u_m"]) > 1e-9 or abs(a1["radius_v_m"] - a2["radius_v_m"]) > 1e-9:
                raise ValueError(f"Seam radius mismatch: {seam_name}")
        seam_checks.append({
            "name": seam_name, "pair": [a, ak, b, bk],
            "shared_center_m": list(ref), "sections": checks,
            "surface_topology_valid": False,
        })
    if len(seam_checks) != 9:
        raise ValueError("Expected exactly nine validated seam centers")
    return seam_checks


def build_scene(profiles: dict, report: dict, seams: list[dict], output: Path) -> None:
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0

    def add_collection(name):
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
        return c

    components_col = add_collection("01_INDEPENDENT_ANATOMICAL_PROXIES")
    seam_col = add_collection("02_SHARED_JOINT_CENTERS")
    notes_col = add_collection("03_GUIDE_NOT_PRODUCTION")

    mats = {}
    for name, rgb in MATERIALS.items():
        m = bpy.data.materials.new(name + "_proxy")
        m.diffuse_color = (*rgb, 1.0)
        mats[name] = m

    # Each proxy gets its own editable Blender mesh. Mesh is created directly;
    # no resizing or touching any Hunyuan mesh or rigged game character.
    def make_loft(name, data, material, coll):
        sections = data["rings"]
        hint = data["axis_hint"]
        verts = []
        n = 20
        for i, sec in enumerate(sections):
            center = Vector(sec["center_m"])
            previous = Vector(sections[max(0, i - 1)]["center_m"])
            following = Vector(sections[min(len(sections) - 1, i + 1)]["center_m"])
            tangent = following - previous
            if tangent.length < 1e-7:
                raise ValueError("Degenerate profile at " + name)
            tangent.normalize()
            preferred = Vector((0, 0, 1)) if hint == "horizontal" else Vector((1, 0, 0))
            u = preferred - tangent * preferred.dot(tangent)
            if u.length < 1e-6:
                preferred = Vector((0, 1, 0))
                u = preferred - tangent * preferred.dot(tangent)
            u.normalize()
            v = tangent.cross(u).normalized()
            for j in range(n):
                angle = 2 * math.pi * j / n
                p = center + u * (sec["radius_u_m"] * math.cos(angle)) + v * (sec["radius_v_m"] * math.sin(angle))
                verts.append(tuple(p))
        faces = []
        faces.append(tuple(reversed(range(n))))
        for i in range(len(sections) - 1):
            for j in range(n):
                nxt = (j + 1) % n
                faces.append((i*n+j, i*n+nxt, (i+1)*n+nxt, (i+1)*n+j))
        faces.append(tuple((len(sections)-1)*n + j for j in range(n)))
        mesh = bpy.data.meshes.new(name + "_MESH")
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        mesh.materials.append(material)
        for poly in mesh.polygons:
            if len(poly.vertices) == 4:
                poly.use_smooth = True
        obj["geometry_status"] = "assumed_depth_proxy_not_reconstruction"
        obj["ready_for_rigging"] = False
        obj["source_master_sha256"] = report["approved_master_sha256"]
        return obj

    for part_id in EXPECTED_PARTS:
        group = bpy.data.collections.new(part_id.upper())
        components_col.children.link(group)
        root = bpy.data.objects.new(part_id + "_CONTROL", None)
        root.empty_display_type = 'PLAIN_AXES'
        root.empty_display_size = 0.045
        group.objects.link(root)
        obj = make_loft(part_id + "_PROXY", profiles[part_id], mats[part_id], group)
        obj.parent = root

    # White seam markers at EXACT shared centers (not a substitute for matching
    # mesh boundaries, seam welding or shoulder / hip socket generation).
    marker_mat = bpy.data.materials.new("shared_center_white")
    marker_mat.diffuse_color = (0.96, 0.96, 0.96, 1)
    for i, item in enumerate(seams, 1):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8,
                                            radius=0.014,
                                            location=item["shared_center_m"])
        obj = bpy.context.object
        obj.name = f"JOINT_{i:02d}_{item['name']}_CENTER_ONLY"
        for old in tuple(obj.users_collection):
            old.objects.unlink(obj)
        seam_col.objects.link(obj)
        obj.data.materials.append(marker_mat)
        obj["surface_fit_valid"] = False
        obj["seam_pair"] = str(item["pair"])

    def add_text(text, loc, size=0.045):
        crv = bpy.data.curves.new("LABEL", 'FONT')
        crv.body = text
        crv.size = size
        obj = bpy.data.objects.new(text, crv)
        obj.location = loc
        obj.rotation_euler = (math.pi / 2, 0, 0)
        notes_col.objects.link(obj)

    add_text("MARA 3D PROXY FITTING", (-0.95, 0.0, 1.86), 0.053)
    add_text("DEPTHS ASSUMED / NO TOPOLOGY FIT / NO HUNYUAN", (-0.95, 0, 1.79), 0.027)

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = False
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1100
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False

    def add_camera(name, pos, focus, scale=2.35):
        bpy.ops.object.camera_add(location=pos)
        cam = bpy.context.object
        cam.name = name
        cam.rotation_euler = (Vector(focus) - cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = scale
        return cam

    front = add_camera('CAMERA_FRONT', (0, -4.5, 0.95), (0, 0, 0.95))
    side = add_camera('CAMERA_SIDE', (4.5, 0, 0.95), (0, 0, 0.95))
    three_q = add_camera('CAMERA_THREE_QUARTER', (3, -4.2, 1.95), (0, 0, 0.90))
    scene.camera = three_q
    filepath = (output / 'mara_depth_proxy.blend').resolve()
    bpy.ops.wm.save_as_mainfile(filepath=str(filepath))
    for cam, filename in [(front, 'front.png'), (side, 'side.png'), (three_q, 'three_quarter.png')]:
        scene.camera = cam
        scene.render.filepath = str((output / filename).resolve())
        bpy.ops.render.render(write_still=True)
    # The .blend was saved with the three-quarter view as its active camera.
    # Do not save again: Blender would create an unnecessary .blend1 backup.


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--master', type=Path, default=DEFAULT_MASTER)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--audit-only', action='store_true',
                        help='Validate inputs and proxy seam centers without Blender')
    args = parser.parse_args(argv)
    try:
        parts, report = audit(args.manifest, args.master)
        profiles = make_profiles(parts)
        seams = validate_seam_centers(profiles, report)
        print(f"PASS: {len(profiles)} separate 3D proxy parts, {len(seams)} shared joint centers")
        print('IMPORTANT: volumes and depth are assumptions; shoulder/hip socket geometry, seam tangents, skinning, and production topology are NOT validated')
        if args.audit_only:
            return 0
        output = args.output.resolve()
        if output.exists():
            raise ValueError('Output directory already exists; use a NEW --output name')
        sources = (args.master.resolve(), args.manifest.resolve())
        if any(output == s or output.is_relative_to(s) or s.is_relative_to(output) for s in sources):
            raise ValueError('Output must be separate from approved input files')
        output.mkdir(parents=True, exist_ok=False)
        report.update({
            'purpose': 'depth_aware_editable_proxy_not_anatomical_reconstruction',
            'generation_locked': True,
            'approved_for_reconstruction': False,
            'profiles': profiles,
            'seam_center_audit': seams,
            'known_missing_work': [
                'No measured or image-derived depth; all radii are assumptions.',
                'Torso shoulder and hip surfaces are not cut into matched sockets.',
                'Joint surface circumference, tangent continuity, manifold assembly are unverified.',
                'Hands are mitten proxies; fingers need independently approved geometry.',
                'Foot forward direction and depth are assumed from T-pose orientation.',
                'No real character mesh, texture, armature, skinning or game-ready export.',
            ],
        })
        (output / 'proxy_audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        build_scene(profiles, report, seams, output)
        print(f'Created: {output / "mara_depth_proxy.blend"}')
        print('Preview: front.png, side.png, three_quarter.png')
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
