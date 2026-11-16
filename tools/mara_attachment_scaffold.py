#!/usr/bin/env python3
"""Mara Venn: build a NON-RECONSTRUCTION 3-D landmark scaffold in Blender.

Input: seam-aware `reference_parts.json` produced by mara_reference_refine.py.
Output: a *new* folder with a Blender scene, front render and audit JSON.

The geometry is a front-plane guide only: all y/depth values are UNKNOWN and
set to zero deliberately. No Hunyuan, Qwen, skinning, model fitting, or GLB
export occurs. Does not modify any image, character card or existing scene.

Audit without Blender:
  python3 tools/mara_attachment_scaffold.py --audit-only

Build a fresh Blender preview from the ai3d project root:
  blender --background --factory-startup --python-exit-code 1 \\
    --python tools/mara_attachment_scaffold.py -- \\
    --output outputs/mara_attachment_scaffold_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

EXPECTED_SHA = "144d06916502ecb524e4113f8bc11b9ab80bfa6714290773a7046d23bd4e2791"
EXPECTED_PARTS = (
    "torso_pelvis", "head", "left_arm", "right_arm", "left_hand", "right_hand",
    "left_leg", "right_leg", "left_foot", "right_foot"
)
EXPECTED_SEAM_COUNT = 9
DEFAULT_MASTER = Path("approved_references/mara_body_front_approved.png")
DEFAULT_MANIFEST = Path("outputs/mara_reference_refine_v1/reference_parts.json")
DEFAULT_OUTPUT = Path("outputs/mara_attachment_scaffold_v1")
MASTER_WIDTH, MASTER_HEIGHT = 512, 512
# This scale is a temporary display assumption, NOT a person measurement.
SCALE_M_PER_PIXEL = 1.70 / (502 - 20)


def read_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_xy(value, description: str) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{description}: must be a [x, y] pair")
    x, y = value
    if (not isinstance(x, (int, float)) or isinstance(x, bool) or
        not isinstance(y, (int, float)) or isinstance(y, bool) or
        not math.isfinite(x) or not math.isfinite(y) or
        not (0 <= x < MASTER_WIDTH) or not (0 <= y < MASTER_HEIGHT)):
        raise ValueError(f"{description}: invalid/out-of-range master pixel coordinates {value!r}")
    return (float(x), float(y))


def to_world(xy: tuple[float, float]) -> tuple[float, float, float]:
    x, y = xy
    # x positive = image right; z positive = up, y = UNKNOWN DEPTH (set 0).
    return ((x - 256) * SCALE_M_PER_PIXEL, 0.0, (502 - y) * SCALE_M_PER_PIXEL)


def audit(manifest_path: Path, master_path: Path) -> tuple[dict, dict]:
    if not manifest_path.is_file():
        raise ValueError(f"Missing seam-aware manifest: {manifest_path}")
    if not master_path.is_file():
        raise ValueError(f"Missing approved master: {master_path}")
    master_sha = read_sha256(master_path)
    if master_sha != EXPECTED_SHA:
        raise ValueError(f"Master checksum mismatch. Expected {EXPECTED_SHA}; found {master_sha}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 2:
        raise ValueError("Expected the version-2 seam-aware reference manifest")
    if not manifest.get("generation_locked") or manifest.get("purpose") != "review_only":
        raise ValueError("Input must be a review-only, generation-locked manifest")
    if manifest.get("master_sha256") != master_sha:
        raise ValueError("Manifest and approved master SHA-256 differ")
    coords = manifest.get("coord_system", {})
    expected_cs = {"origin": "top_left", "x": "image_right", "y": "image_down", "anatomical_left": "viewer_right", "units": "pixels"}
    if not isinstance(coords, dict) or any(coords.get(k) != v for k, v in expected_cs.items()):
        raise ValueError("Unknown coordinate convention in manifest")
    raw_parts = manifest.get("parts")
    if not isinstance(raw_parts, list):
        raise ValueError("Missing parts array")
    parts = {}
    for p in raw_parts:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str):
            raise ValueError("Invalid part entry")
        pid = p["id"]
        if pid in parts:
            raise ValueError(f"Duplicate part: {pid}")
        if p.get("approved_for_inference") is not False:
            raise ValueError(f"Part {pid} has not retained explicit inference lock")
        anchors = p.get("anchors_master_xy")
        if not isinstance(anchors, dict) or not anchors:
            raise ValueError(f"No anchor map: {pid}")
        for label, xy in anchors.items():
            parse_xy(xy, f"{pid}.{label}")
        parts[pid] = p
    if set(parts) != set(EXPECTED_PARTS):
        raise ValueError(f"Expected exactly {list(EXPECTED_PARTS)}, got {list(parts)}")

    seams = manifest.get("seams")
    if not isinstance(seams, list) or len(seams) != EXPECTED_SEAM_COUNT:
        raise ValueError(f"Expected {EXPECTED_SEAM_COUNT} joint pairs")
    report_seams = []
    visited = set()
    for pair in seams:
        if not isinstance(pair, (tuple, list)) or len(pair) != 4:
            raise ValueError(f"Malformed seam: {pair!r}")
        a, akey, b, bkey = pair
        if a not in parts or b not in parts:
            raise ValueError(f"Seam references missing part: {pair}")
        if akey not in parts[a]["anchors_master_xy"] or bkey not in parts[b]["anchors_master_xy"]:
            raise ValueError(f"Seam references missing anchor: {pair}")
        name = f"{a}.{akey}<->{b}.{bkey}"
        if name in visited:
            raise ValueError(f"Duplicate seam: {name}")
        visited.add(name)
        axy = parse_xy(parts[a]["anchors_master_xy"][akey], f"{a}.{akey}")
        bxy = parse_xy(parts[b]["anchors_master_xy"][bkey], f"{b}.{bkey}")
        dist_px = math.dist(axy, bxy)
        # This is 2-D agreement only; physical 3-D joint frame still unknown.
        if dist_px > 2.0:
            raise ValueError(f"Seam endpoints disagree by {dist_px:.2f} pixels: {name}")
        report_seams.append({"pair": list(pair), "endpoint_distance_pixels": round(dist_px, 4), "guide_world_m": list(to_world(axy))})
    report = {
        "version": 1,
        "purpose": "3d_front_plane_attachment_scaffold_only",
        "generation_locked": True,
        "approved_for_reconstruction": False,
        "approved_master_sha256": EXPECTED_SHA,
        "source_manifest": str(manifest_path),
        "parts": list(EXPECTED_PARTS),
        "seams": report_seams,
        "coordinate_mapping": {
            "image_size_px": [512, 512],
            "image_center_x_px": 256,
            "display_floor_y_px": 502,
            "display_crown_y_px": 20,
            "assumed_display_height_m": 1.70,
            "meters_per_pixel": SCALE_M_PER_PIXEL,
            "world_axes": {"x": "image_right", "y": "unknown_depth_assumed_zero", "z": "image_up"},
        },
        "limitations": [
            "No depth was measured; y=0 is only a drawing plane, not a real anatomical fit.",
            "Seam points coincide in 2D, not in 3D surface orientation or circumference.",
            "Part curves show joint chains, not Hunyuan meshes or reconstructed anatomy.",
            "Hands and feet remain low-detail in the approved master and need new references.",
            "Actual game-scale height and body proportions need review before mesh assembly.",
        ],
    }
    return parts, report


def build_blender_preview(parts: dict, report: dict, out_dir: Path) -> None:
    try:
        import bpy  # type: ignore
        from mathutils import Vector  # type: ignore
    except ImportError as exc:
        raise RuntimeError("This step must run inside Blender's Python interpreter") from exc

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0

    def collection(name: str):
        group = bpy.data.collections.new(name)
        scene.collection.children.link(group)
        return group

    raw_col = collection("00_APPROVED_MASTER_GUIDES")
    seam_col = collection("01_SHARED_SEAM_MARKERS")
    skeleton_col = collection("02_ANATOMICAL_PART_GUIDES")
    info_col = collection("03_READ_THIS")

    def color_material(name, color):
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = (*color, 1)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (*color, 1)
            bsdf.inputs["Roughness"].default_value = 0.65
        return mat

    material = {
        "torso_pelvis": color_material("torso_amber", (0.92, 0.65, 0.24)),
        "head": color_material("head_green", (0.28, 0.76, 0.45)),
        "arms": color_material("arms_blue", (0.37, 0.61, 0.90)),
        "hands": color_material("hands_red", (0.92, 0.43, 0.37)),
        "legs": color_material("legs_purple", (0.70, 0.47, 0.86)),
        "feet": color_material("feet_orange", (0.96, 0.55, 0.33)),
        "seams": color_material("seam_white", (0.94, 0.94, 0.85)),
        "text": color_material("label_white", (0.86, 0.91, 0.97)),
    }
    def material_for(pid):
        if pid == "torso_pelvis": return material["torso_pelvis"]
        if pid == "head": return material["head"]
        if pid.endswith("_arm"): return material["arms"]
        if pid.endswith("_hand"): return material["hands"]
        if pid.endswith("_leg"): return material["legs"]
        return material["feet"]

    def create_tube(name, line_xy, dst_col, mat, bevel=0.012):
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        curve.resolution_u = 2
        curve.bevel_depth = bevel
        curve.bevel_resolution = 3
        spline = curve.splines.new('POLY')
        spline.points.add(len(line_xy)-1)
        for i, p in enumerate(line_xy):
            world = to_world(parse_xy(p, name))
            spline.points[i].co = (*world, 1.0)
        obj = bpy.data.objects.new(name, curve)
        dst_col.objects.link(obj)
        obj.data.materials.append(mat)
        return obj

    chains = {
        "torso_pelvis": [
            ("neck", "pelvis_center"),
            ("left_shoulder", "right_shoulder"),
            ("neck", "left_shoulder"), ("neck", "right_shoulder"),
            ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
            ("left_hip", "right_hip"),
        ],
        "head": [("crown", "chin"), ("chin", "neck_joint")],
        "left_arm": [("shoulder", "elbow"), ("elbow", "wrist")],
        "right_arm": [("shoulder", "elbow"), ("elbow", "wrist")],
        "left_hand": [("wrist", "palm"), ("palm", "fingertip_region")],
        "right_hand": [("wrist", "palm"), ("palm", "fingertip_region")],
        "left_leg": [("hip", "knee"), ("knee", "ankle")],
        "right_leg": [("hip", "knee"), ("knee", "ankle")],
        "left_foot": [("ankle", "toe_region")],
        "right_foot": [("ankle", "toe_region")],
    }
    for pid in EXPECTED_PARTS:
        pdata = parts[pid]
        part_col = bpy.data.collections.new(pid.upper())
        skeleton_col.children.link(part_col)
        anchors = pdata["anchors_master_xy"]
        root = bpy.data.objects.new(pid + "_CONTROL", None)
        root.empty_display_type = 'PLAIN_AXES'
        root.empty_display_size = 0.08
        part_col.objects.link(root)
        for anchor_name, raw in anchors.items():
            loc = to_world(parse_xy(raw, f"{pid}.{anchor_name}"))
            guide = bpy.data.objects.new(pid + "_" + anchor_name + "_ANCHOR", None)
            guide.empty_display_type = 'SPHERE'
            guide.empty_display_size = 0.018
            guide.location = loc
            part_col.objects.link(guide)
            guide.parent = root
        for a, b in chains[pid]:
            create_tube(f"{pid}_{a}_{b}_GUIDE", [anchors[a], anchors[b]], part_col, material_for(pid))

    for i, seam in enumerate(report["seams"], 1):
        x, y, z = seam["guide_world_m"]
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.021, location=(x, y, z))
        obj = bpy.context.object
        obj.name = f"SEAM_{i:02d}_2D_ONLY"
        for col in list(obj.users_collection): col.objects.unlink(obj)
        seam_col.objects.link(obj)
        obj.data.materials.append(material["seams"])
        obj["pair"] = " <-> ".join([f"{seam['pair'][0]}.{seam['pair'][1]}", f"{seam['pair'][2]}.{seam['pair'][3]}"])
        obj["3d_fit_valid"] = False

    def add_label(label, pos, size=0.042, mat=None):
        text_curve = bpy.data.curves.new("TEXT_" + label, type='FONT')
        text_curve.body = label
        text_curve.size = size
        text_curve.align_x = 'LEFT'
        o = bpy.data.objects.new("LABEL_" + label, text_curve)
        o.location = pos
        o.rotation_euler = (math.radians(90), 0, 0)
        info_col.objects.link(o)
        if mat: o.data.materials.append(mat)

    add_label("FRONT-PLANE GUIDES ONLY", (-0.90, 0, 1.82), 0.058, material["text"])
    add_label("DEPTH UNKNOWN  |  NO MESH FITTING", (-0.90, 0, 1.75), 0.037, material["text"])

    # Workbench is a reliable lightweight renderer on Blender 4.x and avoids
    # complex external shader setup. Its output is illustrative, not realistic.
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = False
    scene.render.film_transparent = False
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    bpy.ops.object.camera_add(location=(0, -5, 0.87))
    cam = bpy.context.object
    cam.name = "CAMERA_FRONT_ORTHOGRAPHIC"
    cam.rotation_euler = (Vector((0, 0, 0.87)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = 2.35
    scene.camera = cam
    scene.render.filepath = str((out_dir / "front_guide.png").resolve())
    bpy.ops.wm.save_as_mainfile(filepath=str((out_dir / "mara_attachment_scaffold.blend").resolve()))
    bpy.ops.render.render(write_still=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--master', type=Path, default=DEFAULT_MASTER)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        parts, report = audit(args.manifest, args.master)
        print(f"PASS: {len(parts)} parts, {len(report['seams'])} paired seams; SHA-256 verified")
        print("IMPORTANT: 2D anchors only; no observed depth or production geometry")
        if args.audit_only:
            return 0
        out = args.output.resolve()
        srcs = [args.master.resolve(), args.manifest.resolve()]
        if any(src == out or src.is_relative_to(out) or out.is_relative_to(src) for src in srcs):
            raise ValueError("Output must not overlap the master/manifest paths")
        if out.exists():
            raise ValueError(f"Output already exists: {out} (choose a NEW name)")
        import bpy  # type: ignore
        out.mkdir(parents=True, exist_ok=False)
        (out / 'attachment_audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        build_blender_preview(parts, report, out)
        print(f"Created: {out / 'mara_attachment_scaffold.blend'}")
        print(f"Created: {out / 'front_guide.png'}")
        print(f"Created: {out / 'attachment_audit.json'}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
