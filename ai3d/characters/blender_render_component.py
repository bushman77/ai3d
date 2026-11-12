"""Render each standalone GLB from several camera angles in Blender.

Blender invocation:
  blender --background --factory-startup --python-exit-code 1 \
    --python ai3d/characters/blender_render_component.py -- \
    --input outputs/run/05_painted.glb --output-dir outputs/run --part head

No mesh editing, fitting, assembly, CUDA, or source overwrites are performed.
This script runs in Blender's Python interpreter (not the project venv).
"""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


VIEWS = {
    "front": Vector((0.0, -1.0, 0.09)),
    "side": Vector((1.0, 0.0, 0.09)),
    "back": Vector((0.0, 1.0, 0.09)),
    "threequarter": Vector((0.72, -0.72, 0.13)),
}


def arguments():
    parser = argparse.ArgumentParser(description="Render one textured component GLB")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--part", required=True)
    parser.add_argument("--filename-prefix", default="preview",
                        help="Filename prefix for preview images (default: preview)")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def bound_meshes(meshes):
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    if not corners:
        raise RuntimeError("GLB has no mesh geometry to render")
    lower = Vector(tuple(min(v[k] for v in corners) for k in range(3)))
    upper = Vector(tuple(max(v[k] for v in corners) for k in range(3)))
    return (lower + upper) / 2.0, upper - lower


def aim_at(obj, point):
    obj.rotation_euler = (point - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area(name, location, center, watts, size):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = watts
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    aim_at(obj, center)


def main():
    opts = arguments()
    source = opts.input.expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0 or source.suffix.lower() != ".glb":
        raise RuntimeError("Expected a non-empty GLB input: " + str(source))
    directory = opts.output_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    center, size = bound_meshes(meshes)
    span = max(float(max(size)), 0.05)
    distance = span * 2.6

    scene = bpy.context.scene
    # Cycles CPU supports genuine GLB image textures without depending on a
    # GPU/EGL display, even on a 6 GB VRAM laptop in background mode.
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 8
    scene.render.resolution_x = 576
    scene.render.resolution_y = 672
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    scene.view_settings.view_transform = "Standard"

    world = bpy.data.worlds.new("AI3D studio background")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.24, 0.26, 0.29, 1)
    background.inputs["Strength"].default_value = 0.7

    add_area("Key", center + Vector((-distance, -distance, distance)), center, 550, span * 1.6)
    add_area("Fill", center + Vector((distance, -distance, distance * 0.45)), center, 330, span * 1.8)
    add_area("Rim", center + Vector((distance * 0.25, distance, distance)), center, 490, span * 1.6)

    data = bpy.data.cameras.new("AI3D component camera")
    camera = bpy.data.objects.new("AI3D component camera", data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    data.type = "ORTHO"
    aspect = scene.render.resolution_x / scene.render.resolution_y
    data.ortho_scale = max(float(size.z), float(size.x) / aspect,
                           float(size.y) / aspect, 0.05) * 1.32

    for name, direction in VIEWS.items():
        destination = directory / (opts.filename_prefix + "_" + name + ".png")
        if destination.is_file() and destination.stat().st_size > 0 and not opts.force:
            print("AI3D preview reused:", destination, flush=True)
            continue
        camera.location = center + direction.normalized() * distance
        aim_at(camera, center)
        scene.render.filepath = str(destination)
        bpy.ops.render.render(write_still=True)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("Blender did not produce: " + str(destination))
        print("AI3D preview rendered:", destination, flush=True)

    print("AI3D standalone 3D component:", opts.part, source, flush=True)


if __name__ == "__main__":
    main()
