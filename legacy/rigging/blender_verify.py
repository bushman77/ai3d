"""Verify a saved rig scene by reopening the actual .blend in Blender.

This is deliberately a separate process from scene creation. A successful
save/exit alone does not prove that the scene contains the requested model.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy


def args_from_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def validate_scene(scene_path, report):
    loaded = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if loaded != scene_path.resolve():
        raise RuntimeError(f"Rig validation loaded {loaded}, not {scene_path}")

    arm = bpy.data.objects.get("AI3D_Humanoid_Prototype")
    if arm is None or arm.type != "ARMATURE":
        raise RuntimeError("Rig file missing AI3D_Humanoid_Prototype armature")

    expected_bones = {part["name"] for part in report["bones"]}
    actual_bones = set(arm.data.bones.keys())
    if actual_bones != expected_bones or len(actual_bones) < 12:
        raise RuntimeError(
            f"Rig bone mismatch: expected {len(expected_bones)}, got {len(actual_bones)}"
        )

    expected_mesh_names = set(report.get("component_objects", []))
    actual_mesh_names = {
        obj.name for obj in bpy.context.scene.objects if obj.type == "MESH"
    }
    if len(actual_mesh_names) < 2 or not expected_mesh_names <= actual_mesh_names:
        raise RuntimeError("Rig saved without the expected Mara character meshes")

    body = bpy.data.objects.get("AI3D_body_CONTROL")
    if body is None or not any(
        obj.type == "MESH" for obj in body.children_recursive
    ):
        raise RuntimeError("Rig saved without the body mesh hierarchy")

    if bpy.data.objects.get("Cube") and len(actual_mesh_names) == 1:
        raise RuntimeError("Factory startup cube was saved instead of Mara")

    print(
        f"AI3D verified rig: {len(actual_bones)} bones, "
        f"{len(actual_mesh_names)} character meshes, "
        f"source armature {arm.name}",
        flush=True
    )


def main():
    args = args_from_cli()
    source = args.blend.expanduser().resolve(strict=True)
    report_path = args.report.expanduser().resolve(strict=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("skinned") is not False:
        raise RuntimeError("Verifier only supports unskinned prototypes")
    validate_scene(source, report)


if __name__ == "__main__":
    main()
