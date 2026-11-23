#!/usr/bin/env python3
"""Blender headless multi-view solid inspection of one existing GLB; never edits GLB."""
import argparse
import json
import math
from pathlib import Path
import sys


def main():
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mesh', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    if not args.mesh.is_file():
        p.error(f'GLB missing: {args.mesh}')
    if args.output.exists():
        p.error(f'Review output already exists: {args.output}; use a fresh run')
    import bpy
    from mathutils import Vector
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.mesh.resolve()))
    objs = [o for o in bpy.context.scene.objects if o.type == 'MESH' and len(o.data.vertices)]
    if not objs:
        raise RuntimeError('No mesh objects in GLB')
    points=[]
    for o in objs:
        points.extend([o.matrix_world @ Vector(c) for c in o.bound_box])
    low=Vector(tuple(min(v[i] for v in points) for i in range(3)))
    high=Vector(tuple(max(v[i] for v in points) for i in range(3)))
    center=(low+high)/2
    span=max((high-low).length, 0.01)
    scene=bpy.context.scene
    scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.light='STUDIO'
    scene.display.shading.color_type='SINGLE'
    scene.display.shading.single_color=(0.72,0.75,0.80)
    scene.display.shading.show_shadows=True
    scene.render.resolution_x=800
    scene.render.resolution_y=800
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    positions={
        'front': Vector((0,-1,0)),
        'side': Vector((1,0,0)),
        'back': Vector((0,1,0)),
        'three_quarter': Vector((0.65,-1,0.3)).normalized(),
    }
    args.output.mkdir(parents=True)
    for name, direction in positions.items():
        bpy.ops.object.camera_add(location=center+direction*span*2.5)
        camera=bpy.context.object
        camera.name='QA_CAM_'+name
        camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='ORTHO'
        camera.data.ortho_scale=span*1.22
        scene.camera=camera
        scene.render.filepath=str((args.output / (name+'.png')).resolve())
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(camera,do_unlink=True)
    report={'mesh':str(args.mesh.resolve()),
            'objects':len(objs), 'vertices':sum(len(o.data.vertices) for o in objs),
            'triangles':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in objs),
            'bounds_min':list(low), 'bounds_max':list(high),
            'solid_views':list(positions),
            'status':'review_only_not_automatic_geometry_approval'}
    (args.output/'mesh_review.json').write_text(json.dumps(report, indent=2))
    print('Review images:',args.output)

if __name__=='__main__':
    main()
