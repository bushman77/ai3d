import bpy
from mathutils import Vector
from pathlib import Path

# Work from the scene currently open in Blender, including saved bone edits.
if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
source = Path(bpy.data.filepath)
if not source.is_file():
    raise RuntimeError('First open your manually fitted rig .blend file')
out = source.with_name('mara_ground_aligned.blend')
if out.exists():
    raise RuntimeError('Output already exists; nothing changed: ' + str(out))
if bpy.data.objects.get('MARA_ROOT'):
    raise RuntimeError('MARA_ROOT already exists; nothing changed')

names = (
    'AI3D_body_CONTROL', 'AI3D_equipment_CONTROL',
    'AI3D_hands_CONTROL', 'AI3D_head_CONTROL',
    'AI3D_lower_outfit_CONTROL', 'AI3D_upper_outfit_CONTROL',
    'AI3D_Humanoid_Prototype',
)
roots = [bpy.data.objects.get(n) for n in names]
if any(obj is None or obj.parent is not None for obj in roots):
    raise RuntimeError('Expected seven unparented Mara rig/component roots')
arm = bpy.data.objects['AI3D_Humanoid_Prototype']
if arm.type != 'ARMATURE' or 'pelvis' not in arm.data.bones:
    raise RuntimeError('Missing Mara armature or pelvis bone')
meshes = [obj for obj in bpy.context.scene.objects
          if obj.type == 'MESH' and obj.visible_get() and not obj.hide_render]
if not meshes:
    raise RuntimeError('No visible character meshes')
min_z = min((obj.matrix_world @ Vector(corner)).z
            for obj in meshes for corner in obj.bound_box)
pelvis = arm.matrix_world @ arm.data.bones['pelvis'].head_local

root = bpy.data.objects.new('MARA_ROOT', None)
bpy.context.scene.collection.objects.link(root)
root.empty_display_type = 'SPHERE'
root.empty_display_size = 0.08
root.location = (pelvis.x, pelvis.y, min_z)
bpy.context.view_layer.update()
for obj in roots:
    old_world = obj.matrix_world.copy()
    obj.parent = root
    obj.matrix_world = old_world
bpy.context.view_layer.update()
root.location = (0, 0, 0)
bpy.context.view_layer.update()
new_min_z = min((obj.matrix_world @ Vector(corner)).z
                for obj in meshes for corner in obj.bound_box)
print('Original ground Z:', round(min_z, 6))
print('New ground Z:', round(new_min_z, 6))
print('Pelvis center before:', tuple(round(c, 6) for c in pelvis))
print('Saved new scene:', str(out))
bpy.ops.wm.save_as_mainfile(filepath=str(out))
