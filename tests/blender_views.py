"""Render sharp orthographic front/back/left/right views of a GLB and save a
copy with a plain grey texture (no detail), standing in for Paint3D output.

blender --background --factory-startup --python tests/blender_views.py -- SRC.glb OUTDIR
Not a unit test (needs Blender); used by test_blender_stages.py.
"""
import bpy, sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai3d" / "blender"))
from common import *  # noqa
import quality as q
from mathutils import Vector
src, outdir = sys.argv[-2], sys.argv[-1]
reset_scene()
objs=[o for o in import_glb(src) if o.type=="MESH"]
cam=q.setup_render(512)
bpy.context.scene.render.film_transparent=True
lo,hi=q.bounds(objs); mid=(lo+hi)/2; span=max(hi-lo)*1.1; d=span*2
cam.data.ortho_scale=span
for name,loc,rot in (("front",(0,-d,0),(90,0,0)),("back",(0,d,0),(90,0,180)),("left",(d,0,0),(90,0,90)),("right",(-d,0,0),(90,0,-90))):
    cam.location=mid+Vector(loc); cam.rotation_euler=[math.radians(r) for r in rot]
    bpy.context.scene.render.filepath=f"{outdir}/view_{name}.png"; bpy.ops.render.render(write_still=True)
# detail-free 'paint3d' copy: plain grey texture, so any pattern in a bake
# of it must have come from the projected views
for im in bpy.data.images:
    if im.size[0] > 64:
        im.pixels.foreach_set([0.5] * (im.size[0] * im.size[1] * 4))
        im.pack()
export_glb(Path(f"{outdir}/blurry.glb"), objs)
