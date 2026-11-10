"""Blender 4.1+ static-mesh optimization of an ALREADY TEXTURED GLB.

This uses the existing non-destructive strategy: preserve mesh UV layers,
image textures and materials when reducing polygon count. It does not weld UV
seams. The export intentionally excludes animation and non-mesh scene objects;
therefore this backend is for unrigged static assets, not animated characters.
Requires Blender's bundled `bpy` when performing an actual export.
"""

import argparse
from pathlib import Path
import sys


def tris(obj):
    """Count triangles, including triangles created by triangulating n-gons."""
    return sum(max(0, len(poly.vertices) - 2) for poly in obj.data.polygons)


def parse_arguments(argv=None):
    """Validate paths/options before loading Blender, allowing lightweight tests."""
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Optimize an already-textured static GLB")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-faces", type=int, default=15000,
                        help="Maximum approximate total triangle count")
    args = parser.parse_args(argv)
    source = Path(args.input).expanduser().resolve()
    target = Path(args.output).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".glb":
        parser.error(f"Source missing: {source}")
    if target == source or target.suffix.lower() != ".glb":
        parser.error("Output must be a distinct .glb file")
    if args.target_faces < 100:
        parser.error("--target-faces must be >= 100")
    return args, source, target


def main():
    args, source, target = parse_arguments()

    # Blender's Python is only required when running the actual mesh stage.
    import bpy

    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh found in textured GLB")
    if not any(obj.data.uv_layers for obj in meshes):
        raise RuntimeError("Textured model has no UV layers; refusing to export")
    images = [image for image in bpy.data.images if image.size[0] > 0 and image.size[1] > 0]
    if not images:
        raise RuntimeError("No texture images loaded; refusing texture-stripping export")

    count = sum(tris(obj) for obj in meshes)
    print(f"Loaded {len(meshes)} mesh(es), {count:,} triangles, {len(images)} images", flush=True)
    if count > args.target_faces:
        ratio = args.target_faces / count
        for obj in meshes:
            if tris(obj) == 0:
                continue
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new("AI3D final decimation", "DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            bpy.ops.object.modifier_apply(modifier=mod.name)
            obj.select_set(False)
    print(f"Optimized triangles: {sum(tris(obj) for obj in meshes):,}", flush=True)

    # Do NOT weld after UV unwrapping: that can destroy texture seams.
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]

    bpy.ops.export_scene.gltf(
        filepath=str(target),
        export_format="GLB",
        use_selection=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_animations=False,
    )
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("GLB export failed")
    print(f"Exported {target}: {target.stat().st_size / 1024:.0f} KiB", flush=True)


if __name__ == "__main__":
    main()
