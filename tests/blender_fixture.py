"""Build a crude textured humanoid GLB for exercising the Blender stages.

blender --background --factory-startup --python tests/blender_fixture.py -- OUT.glb [--pose a|t] [--face +y|-y] [--hips narrow|wide]

Not a unit test (needs Blender). The mannequin is overlapping primitives,
like a raw Hunyuan mesh: several intersecting shells, 1.75 m tall, feet on
Z=0, facing -Y by default (toes point forward).
"""
import math
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out = Path(args[0]) if args else Path("/tmp/ai3d_mannequin.glb")
pose = args[args.index("--pose") + 1] if "--pose" in args else "a"
face = args[args.index("--face") + 1] if "--face" in args else "-y"
hips = args[args.index("--hips") + 1] if "--hips" in args else "narrow"

bpy.ops.wm.read_factory_settings(use_empty=True)
parts = []


def add(op, **kw):
    op(**kw)
    obj = bpy.context.active_object
    parts.append(obj)
    return obj


def limb(a, b, r):
    a, b = map(lambda v: __import__("mathutils").Vector(v), (a, b))
    d = b - a
    obj = add(bpy.ops.mesh.primitive_cylinder_add, vertices=16, radius=r, depth=d.length,
              location=(a + b) / 2)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = d.to_track_quat("Z", "Y")
    add(bpy.ops.mesh.primitive_uv_sphere_add, segments=16, ring_count=8, radius=r, location=b)
    return obj


add(bpy.ops.mesh.primitive_uv_sphere_add, segments=24, ring_count=16, radius=0.11, location=(0, 0, 1.63))
add(bpy.ops.mesh.primitive_cylinder_add, vertices=16, radius=0.05, depth=0.12, location=(0, 0, 1.50))
torso = add(bpy.ops.mesh.primitive_uv_sphere_add, segments=24, ring_count=16, radius=1, location=(0, 0, 1.18))
torso.scale = (0.19, 0.12, 0.32)
pelvis = add(bpy.ops.mesh.primitive_uv_sphere_add, segments=24, ring_count=16, radius=1, location=(0, 0, 0.93))
pelvis.scale = (0.17, 0.11, 0.14) if hips == "narrow" else (0.24, 0.12, 0.22)
drop = 0.0 if pose == "t" else math.radians(40)
for s in (1, -1):
    sh = (s * 0.19, 0, 1.40)
    reach = 0.62
    hand = (s * (0.19 + reach * math.cos(drop)), 0, 1.40 - reach * math.sin(drop))
    elbow = tuple((sh[i] + hand[i]) / 2 for i in range(3))
    # Shoulder ball joins the arm to the torso (otherwise the arm floats).
    add(bpy.ops.mesh.primitive_uv_sphere_add, segments=16, ring_count=8, radius=0.075,
        location=(s * 0.15, 0, 1.38))
    limb(sh, elbow, 0.045)
    limb(elbow, hand, 0.038)
    hp = add(bpy.ops.mesh.primitive_uv_sphere_add, segments=12, ring_count=8, radius=1, location=hand)
    hp.scale = (0.08, 0.03, 0.05)
    hip = (s * 0.09, 0, 0.88)
    knee = (s * 0.10, 0, 0.48)
    ankle = (s * 0.10, 0, 0.08)
    limb(hip, knee, 0.07)
    limb(knee, ankle, 0.05)
    foot = add(bpy.ops.mesh.primitive_cube_add, size=1, location=(s * 0.10, -0.07, 0.04))
    foot.scale = (0.09, 0.24, 0.08)

for obj in parts:
    obj.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
body = bpy.context.active_object
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if face == "+y":
    body.rotation_euler[2] = math.pi
    bpy.ops.object.transform_apply(rotation=True)
bpy.ops.object.shade_smooth()

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
bpy.ops.object.mode_set(mode="OBJECT")

# Like Paint3D: colour only inside the UV islands, black gutters between
# them. Baked from a procedural checker with no margin.
img = bpy.data.images.new("fixture_albedo", 512, 512)
img.generated_color = (0, 0, 0, 1)
mat = bpy.data.materials.new("fixture")
mat.use_nodes = True
nodes, links = mat.node_tree.nodes, mat.node_tree.links
bsdf = nodes["Principled BSDF"]
checker = nodes.new("ShaderNodeTexChecker")
checker.inputs["Scale"].default_value = 12
checker.inputs["Color1"].default_value = (0.75, 0.45, 0.20, 1)
checker.inputs["Color2"].default_value = (0.20, 0.45, 0.70, 1)
coords = nodes.new("ShaderNodeTexCoord")
links.new(coords.outputs["Object"], checker.inputs["Vector"])
links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
tex = nodes.new("ShaderNodeTexImage")
tex.image = img
body.data.materials.append(mat)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 1
scene.render.bake.margin = 0
body.select_set(True)
bpy.context.view_layer.objects.active = body
nodes.active = tex
bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"})
img.pack()
links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

out.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB")
print("fixture:", out, len(body.data.polygons), "faces")
