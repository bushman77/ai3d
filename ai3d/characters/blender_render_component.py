"""Blender background renderer for an isolated generated component GLB.

Creates front, three-quarter and side PNGs. No assembly or mesh modification.
Run: blender -b --factory-startup --python-exit-code 1
     --python blender_render_component.py -- --input path/06_game.glb
"""
import argparse
from pathlib import Path
import sys


VIEWS = {
    "front": (0.0, -1.0, 0.0),
    "threequarter": (0.65, -0.85, 0.18),
    "side": (1.0, 0.0, 0.0),
}


def parse_args():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--size", type=int, default=640)
    return parser.parse_args(args)


def render_component(source: Path, size: int):
    import bpy
    from mathutils import Vector

    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError(f"Component GLB is absent or empty: {source}")
    if size < 64:
        raise RuntimeError("Preview image size must be >= 64")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source.resolve()))
    meshes = [ob for ob in bpy.context.scene.objects if ob.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"GLB has no mesh: {source}")

    corners = [ob.matrix_world @ Vector(corner) for ob in meshes
               for corner in ob.bound_box]
    lo = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
    center = (lo + hi) * 0.5
    dims = hi - lo
    extent = max(dims.x, dims.y, dims.z, 0.01)
    scene = bpy.context.scene
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    # EEVEE displays actual glTF materials; Workbench remains a fallback for
    # machines without a usable graphical render context.
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    else:
        scene.render.engine = "BLENDER_WORKBENCH"
    if scene.render.engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = 16

    world = bpy.data.worlds.new("AI3D neutral studio")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.35, 0.38, 0.42, 1.0)
    background.inputs["Strength"].default_value = 0.85

    camera_data = bpy.data.cameras.new("AI3D preview camera")
    camera = bpy.data.objects.new("AI3D preview camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = extent * 1.48

    for label, offset, power in (
        ("Key", (-1.5, -2.0, 2.0), 420),
        ("Fill", (1.8, -0.8, 1.0), 260),
        ("Rim", (0.3, 2.0, 1.6), 360),
    ):
        light_data = bpy.data.lights.new(f"AI3D {label}", type="AREA")
        light = bpy.data.objects.new(f"AI3D {label}", light_data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset) * extent
        direction = center - light.location
        light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        light_data.energy = power * max(extent, 0.1) ** 2
        light_data.shape = "DISK"
        light_data.size = extent * 1.7

    output = source.parent
    for view, direction in VIEWS.items():
        camera.location = center + Vector(direction).normalized() * extent * 2.8
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        path = output / f"07_preview_{view}.png"
        scene.render.filepath = str(path)
        try:
            bpy.ops.render.render(write_still=True)
        except Exception as exc:
            if scene.render.engine == "BLENDER_WORKBENCH":
                raise
            print(f"[RENDER] {view}: material render unavailable ({exc}); using Workbench")
            scene.render.engine = "BLENDER_WORKBENCH"
            scene.display.shading.light = "STUDIO"
            scene.display.shading.color_type = "MATERIAL"
            bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing preview after render: {path}")
        print(f"[PREVIEW] {path}", flush=True)


if __name__ == "__main__":
    options = parse_args()
    render_component(options.input, options.size)
