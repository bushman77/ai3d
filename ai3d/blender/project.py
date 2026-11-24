"""Paint the game mesh straight from sharp character views (run inside Blender).

Used by retopo_bake.py after the Paint3D colour has been baked. Each view is
an orthographic picture of the character (front, back, left, right). Every
vertex takes its colour from the views that face it most directly and can
actually see it (ray test, so an arm in front of the body doesn't paint the
body). Where no view sees well (top of the head, under the arms) the baked
Paint3D colour stays. The result is baked into the game mesh's own UVs.

Alignment is automatic: the character's outline in each picture is fitted
to the mesh outline seen from that side, and side views are flipped
whichever way matches the mesh better.
"""
from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import numpy as np

# camera direction (from the character towards the camera), image-right axis
FRONT = (Vector((0, -1, 0)), Vector((1, 0, 0)))
BACK = (Vector((0, 1, 0)), Vector((-1, 0, 0)))
SIDE_PLUS_X = (Vector((1, 0, 0)), Vector((0, 1, 0)))
SIDE_MINUS_X = (Vector((-1, 0, 0)), Vector((0, -1, 0)))


def load_view(path: Path):
    """Image with its background filled (no dark fringes) and the alpha bbox."""
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    mask = px[..., 3] > 0.5
    rows, cols = np.where(mask)
    if rows.size == 0:
        raise RuntimeError(f"{path} has no visible character (empty alpha)")
    bbox = (cols.min(), cols.max() + 1, rows.min(), rows.max() + 1)  # x0 x1 y0 y1, bottom-up
    rgb = px[..., :3] * mask[..., None]
    grow_mask = mask.copy()
    for _ in range(24):
        total = np.zeros_like(rgb)
        count = np.zeros(mask.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            total += np.roll(rgb, (dy, dx), axis=(0, 1))
            count += np.roll(grow_mask, (dy, dx), axis=(0, 1))
        grow = (~grow_mask) & (count > 0)
        rgb[grow] = total[grow] / count[grow][:, None]
        grow_mask |= grow
    px[..., :3] = rgb
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.update()
    img.pack()
    return img, bbox, mask


def mesh_silhouette(tree, lo, hi, to_cam, right, grid=96):
    """Boolean outline of the mesh seen from `to_cam` (rows top-down)."""
    up = Vector((0, 0, 1))
    centre = (lo + hi) / 2
    reach = (hi - lo).length
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    us = [c.dot(right) for c in corners]
    u0, u1, z0, z1 = min(us), max(us), lo.z, hi.z
    w = max(8, round(grid * (u1 - u0) / max(1e-6, z1 - z0)))
    sil = np.zeros((grid, w), dtype=bool)
    for r in range(grid):
        z = z1 - (r + 0.5) * (z1 - z0) / grid
        for c in range(w):
            u = u0 + (c + 0.5) * (u1 - u0) / w
            origin = centre + right * (u - centre.dot(right)) + up * (z - centre.z) + to_cam * reach
            sil[r, c] = tree.ray_cast(origin, -to_cam, 2 * reach)[0] is not None
    rows, cols = np.where(sil)
    return sil[rows.min():rows.max() + 1, cols.min():cols.max() + 1] if rows.size else sil


def image_outline(mask, shape):
    """Alpha mask cropped to its bbox, resampled to `shape`, rows top-down."""
    m = mask[::-1]
    rows, cols = np.where(m)
    crop = m[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    h, w = shape
    ri = ((np.arange(h) + 0.5) * crop.shape[0] / h).astype(int)
    ci = ((np.arange(w) + 0.5) * crop.shape[1] / w).astype(int)
    return crop[ri[:, None], ci[None, :]]


def iou(a, b):
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def choose_orientation(kind, mask, tree, lo, hi):
    """Camera setup for a view; side views pick whichever side fits best."""
    options = {"front": [FRONT], "back": [BACK],
               "left": [SIDE_PLUS_X, SIDE_MINUS_X], "right": [SIDE_MINUS_X, SIDE_PLUS_X]}[kind]
    scored = []
    for to_cam, right in options:
        sil = mesh_silhouette(tree, lo, hi, to_cam, right)
        scored.append((iou(sil, image_outline(mask, sil.shape)), to_cam, right))
    best = max(scored, key=lambda s: s[0])
    return best


def project(low, views, base_image, uv_main, *, power=3.0, base_weight=0.02, samples=1,
            min_match=0.7):
    """Bake a projection-blended colour over `base_image` (in place).

    views: list of (kind, path). Returns per-view stats.
    """
    mesh = low.data
    mw = low.matrix_world
    deps = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(low, deps)
    world = [mw @ v.co for v in mesh.vertices]
    normals = [(mw.to_3x3() @ v.normal).normalized() for v in mesh.vertices]
    lo = Vector((min(p.x for p in world), min(p.y for p in world), min(p.z for p in world)))
    hi = Vector((max(p.x for p in world), max(p.y for p in world), max(p.z for p in world)))
    height = (hi.z - lo.z) or 1.0

    mat = bpy.data.materials.new("AI3D_PROJECT")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    links.new(emit.outputs["Emission"], out.inputs["Surface"])

    def uv_image(image, uv_name):
        uvn = nodes.new("ShaderNodeUVMap")
        uvn.uv_map = uv_name
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.extension = "EXTEND"
        tex.interpolation = "Cubic"
        links.new(uvn.outputs["UV"], tex.inputs["Vector"])
        return tex.outputs["Color"]

    def scale(colour, factor):
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = "SCALE"
        links.new(colour, node.inputs[0])
        links.new(factor, node.inputs["Scale"])
        return node.outputs["Vector"]

    def add(a, b, vector=True):
        node = nodes.new("ShaderNodeVectorMath" if vector else "ShaderNodeMath")
        node.operation = "ADD"
        links.new(a, node.inputs[0])
        links.new(b, node.inputs[1])
        return node.outputs[0]

    def weight_output(attr_name):
        attr = nodes.new("ShaderNodeVertexColor")
        attr.layer_name = attr_name
        sep = nodes.new("ShaderNodeSeparateColor")
        links.new(attr.outputs["Color"], sep.inputs["Color"])
        return sep.outputs[0]

    base_w = nodes.new("ShaderNodeValue")
    base_w.outputs[0].default_value = base_weight
    colour_sum = scale(uv_image(base_image, uv_main), base_w.outputs[0])
    weight_sum = base_w.outputs[0]
    stats = []

    for kind, path in views:
        img, (x0, x1, y0, y1), mask = load_view(Path(path))
        W, H = img.size
        edges = [e for e, hit in (("bottom", y0 <= 1), ("top", y1 >= H - 1),
                                  ("left", x0 <= 1), ("right", x1 >= W - 1)) if hit]
        if edges:
            # Cut off (e.g. top of the head): the outline box no longer spans
            # the whole figure, so the alignment would slide colours around.
            print(f"[project] skipping {kind}: figure touches the {', '.join(edges)} edge",
                  flush=True)
            stats.append({"view": kind, "file": str(path), "skipped": True, "cut_off": edges})
            continue
        fit, to_cam, right = choose_orientation(kind, mask, tree, lo, hi)
        if fit < min_match:
            # A view that doesn't line up would paint colours onto the wrong
            # body parts; keep Paint3D's colour there instead.
            print(f"[project] skipping {kind}: outline match {fit:.2f} < {min_match}", flush=True)
            stats.append({"view": kind, "file": str(path), "outline_match": round(fit, 3),
                          "skipped": True})
            continue
        us = [p.dot(right) for p in world]
        u_lo, u_hi = min(us), max(us)
        uv_name = f"proj_{kind}"
        layer = mesh.uv_layers.new(name=uv_name)
        for loop in mesh.loops:
            p = world[loop.vertex_index]
            un = (p.dot(right) - u_lo) / max(1e-6, u_hi - u_lo)
            vn = (p.z - lo.z) / height
            layer.data[loop.index].uv = ((x0 + un * (x1 - x0)) / W, (y0 + vn * (y1 - y0)) / H)
        attr_name = f"w_{kind}"
        attr = mesh.color_attributes.new(attr_name, "FLOAT_COLOR", "POINT")
        seen = 0
        for i, (p, n) in enumerate(zip(world, normals)):
            facing = n.dot(to_cam)
            w = 0.0
            if facing > 0.05:
                hit = tree.ray_cast(p + to_cam * (0.002 * height), to_cam, 4 * height)
                if hit[0] is None:
                    w = facing ** power
                    seen += 1
            attr.data[i].color = (w, w, w, 1.0)
        colour = uv_image(img, uv_name)
        wout = weight_output(attr_name)
        colour_sum = add(colour_sum, scale(colour, wout))
        weight_sum = add(weight_sum, wout, vector=False)
        stats.append({"view": kind, "file": str(path), "outline_match": round(fit, 3),
                      "camera": [round(c, 2) for c in to_cam],
                      "vertices_seen": round(seen / max(1, len(world)), 3)})

    inv = nodes.new("ShaderNodeMath")
    inv.operation = "DIVIDE"
    inv.inputs[0].default_value = 1.0
    links.new(weight_sum, inv.inputs[1])
    links.new(scale(colour_sum, inv.outputs[0]), emit.inputs["Color"])

    target = nodes.new("ShaderNodeTexImage")
    result = bpy.data.images.new("ai3d_projected", base_image.size[0], base_image.size[1],
                                 alpha=False)
    target.image = result
    nodes.active = target

    saved = list(low.data.materials)
    low.data.materials.clear()
    low.data.materials.append(mat)
    mesh.uv_layers.active = mesh.uv_layers[uv_main]
    for layer in mesh.uv_layers:
        layer.active_render = layer.name == uv_main
    scene = bpy.context.scene
    scene.render.bake.use_selected_to_active = False
    scene.cycles.samples = samples
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj == low)
    bpy.context.view_layer.objects.active = low
    bpy.ops.object.bake(type="EMIT")

    base_image.pixels.foreach_set(np.array(result.pixels[:], dtype=np.float32))
    base_image.update()
    low.data.materials.clear()
    for m in saved:
        low.data.materials.append(m)
    for item in stats:
        if item.get("skipped"):
            continue
        mesh.uv_layers.remove(mesh.uv_layers[f"proj_{item['view']}"])
        mesh.color_attributes.remove(mesh.color_attributes[f"w_{item['view']}"])
    return stats

