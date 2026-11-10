"""Blender 4.1+ (background) optimization of ALREADY TEXTURED GLB.

Unlike the geometry-only optimize_mesh.py script, this does NOT strip materials,
UV layers or embedded images. It also deliberately does not weld UV seams.
"""
import argparse
import sys
from pathlib import Path
import bpy


def tris(obj):
    return sum(max(0, len(poly.vertices) - 2) for poly in obj.data.polygons)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--target-faces", type=int, default=15000)
    a = ap.parse_args(argv)
    source = Path(a.input).expanduser().resolve()
    target = Path(a.output).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".glb":
        ap.error(f"Source missing: {source}")
    if target == source or target.suffix.lower() != ".glb":
        ap.error("Output must be a distinct .glb file")
    if a.target_faces < 100:
        ap.error("--target-faces must be >= 100")
    target.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh found in textured GLB")
    if not any(obj.data.uv_layers for obj in meshes):
        raise RuntimeError("Textured model has no UV layers; refusing to export")
    images = [img for img in bpy.data.images if img.size[0] > 0 and img.size[1] > 0]
    if not images:
        raise RuntimeError("No texture images loaded; refusing texture-stripping export")

    count = sum(tris(obj) for obj in meshes)
    print(f"Loaded {len(meshes)} mesh(es), {count:,} triangles, {len(images)} images", flush=True)
    if count > a.target_faces:
        ratio = a.target_faces / count
        for obj in meshes:
            if tris(obj) == 0:
                continue
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new("Space Nova final decimation", "DECIMATE")
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
