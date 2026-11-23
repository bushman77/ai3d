"""Helpers shared by AI3D Blender scripts. Imported only inside Blender.

Each script in this folder adds its own directory to sys.path and then
does `from common import ...`, so this works with `blender --python`.
"""
import json
import sys
from pathlib import Path

import bpy


def script_args() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path: Path) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [obj for obj in bpy.data.objects if obj not in before]


def select_only(objects, active=None) -> None:
    bpy.context.view_layer.update()
    for obj in bpy.context.view_layer.objects:
        if obj is not None:
            obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or (objects[0] if objects else None)


def join_meshes(objects, name: str):
    """Join every imported mesh into one object with transforms applied."""
    meshes = [obj for obj in objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh found in the GLB")
    # Unparent while keeping transforms so join/apply works on any hierarchy.
    select_only(meshes)
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    select_only([obj])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for other in list(bpy.data.objects):
        if other is not obj and other.type in {"EMPTY"}:
            bpy.data.objects.remove(other, do_unlink=True)
    obj.name = name
    obj.data.name = name
    return obj


def triangle_count(obj) -> int:
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def export_glb(path: Path, objects, *, animations: bool = False, apply_modifiers: bool = True) -> None:
    """Export only `objects`. Never apply modifiers on skinned exports."""
    select_only(objects)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(path), export_format="GLB", use_selection=True,
        export_apply=apply_modifiers, export_animations=animations,
        export_yup=True,
    )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
