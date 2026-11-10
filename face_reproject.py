#!/usr/bin/env python3
"""Space Nova: front-view face texture correction for an existing textured GLB.

This is an intentionally conservative *non-AI* correction pass: it projects pixels
from a front character cutout onto the face region of the existing base-color atlas.
Geometry, UVs, normal maps, and other PBR data are left unchanged. Existing input
GLB is never overwritten.

Requires: numpy, Pillow. Runs in Hunyuan3D's existing Python environment.
"""

import argparse
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
          5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NUM_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(path):
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("Not a binary glTF (GLB) file")
    _, version, length = struct.unpack_from("<4sII", data)
    if version != 2 or length != len(data):
        raise ValueError("Invalid GLB header/length")
    offset = 12
    chunks = []
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        chunks.append((kind, data[offset:offset + size]))
        offset += size
    if offset != len(data):
        raise ValueError("Invalid GLB chunk layout")
    json_parts = [blob for kind, blob in chunks if kind == JSON_CHUNK]
    bin_parts = [blob for kind, blob in chunks if kind == BIN_CHUNK]
    if len(json_parts) != 1 or len(bin_parts) != 1:
        raise ValueError("Expected exactly one JSON and one BIN chunk")
    doc = json.loads(json_parts[0].decode("utf-8"))
    if len(doc.get("buffers", [])) != 1:
        raise ValueError("Only single-buffer GLBs are supported")
    return doc, bin_parts[0], chunks


def accessor_array(doc, binary, index):
    ac = doc["accessors"][index]
    if "sparse" in ac:
        raise ValueError("Sparse accessors are not supported")
    view = doc["bufferViews"][ac["bufferView"]]
    if view.get("buffer", 0) != 0:
        raise ValueError("Expected data in GLB binary buffer")
    typ = np.dtype(DTYPES[ac["componentType"]]).newbyteorder("<")
    cols = NUM_COMPONENTS[ac["type"]]
    item_bytes = typ.itemsize * cols
    stride = view.get("byteStride", item_bytes)
    if stride < item_bytes:
        raise ValueError("Invalid accessor byte stride")
    start = view.get("byteOffset", 0) + ac.get("byteOffset", 0)
    end = start + ((ac["count"] - 1) * stride + item_bytes)
    if end > len(binary):
        raise ValueError("Accessor points outside BIN chunk")
    result = np.ndarray((ac["count"], cols), dtype=typ,
                        buffer=binary, offset=start,
                        strides=(stride, typ.itemsize)).copy()
    return result[:, 0] if cols == 1 else result


def extract_image(doc, binary, index):
    info = doc["images"][index]
    if "bufferView" not in info:
        raise ValueError("Expected an embedded base-color image")
    view = doc["bufferViews"][info["bufferView"]]
    start = view.get("byteOffset", 0)
    size = view["byteLength"]
    if start + size > len(binary):
        raise ValueError("Image points beyond binary data")
    return Image.open(io.BytesIO(binary[start:start + size])).convert("RGB")


def smooth01(x):
    v = np.clip(x, 0, 1)
    return v * v * (3 - 2 * v)


def bilinear_rgba(arr, px, py):
    """Sample an RGBA image at float pixel positions, clipping at boundaries."""
    height, width, _ = arr.shape
    px = np.clip(px, 0, width - 1)
    py = np.clip(py, 0, height - 1)
    ix, iy = np.floor(px).astype(np.int32), np.floor(py).astype(np.int32)
    jx, jy = np.minimum(ix + 1, width - 1), np.minimum(iy + 1, height - 1)
    fx, fy = (px - ix)[:, None], (py - iy)[:, None]
    top = arr[iy, ix] * (1 - fx) + arr[iy, jx] * fx
    bot = arr[jy, ix] * (1 - fx) + arr[jy, jx] * fx
    return top * (1 - fy) + bot * fy


def patch_atlas(base, ref, positions, normals, uv, indices, args):
    atlas = np.array(base.convert("RGB"), dtype=np.uint8)
    target_height, target_width, _ = atlas.shape
    source = np.array(ref.convert("RGBA"), dtype=np.float32)
    source_height, source_width, _ = source.shape
    alpha_bounds = ref.convert("RGBA").getchannel("A").getbbox()
    if alpha_bounds is None:
        raise ValueError("Reference image contains no visible character")
    left, top, right, bottom = alpha_bounds
    minx, miny = positions[:, :2].min(axis=0)
    maxx, maxy = positions[:, :2].max(axis=0)
    spanx, spany = max(maxx - minx, 1e-8), max(maxy - miny, 1e-8)
    midx = (minx + maxx) / 2
    front_sign = 1 if args.front == "+z" else -1
    uv_pixels = np.column_stack((uv[:, 0] * (target_width - 1),
                                 (1 - uv[:, 1]) * (target_height - 1)))
    out = atlas.astype(np.float32)
    # Higher front-facing depth wins when multiple triangles map to the same texel.
    depth = np.full((target_height, target_width), -np.inf, dtype=np.float32)
    contributions = 0
    edited = 0

    for tri in indices:
        tri = np.asarray(tri, dtype=np.int32)
        p = positions[tri].astype(np.float32)
        n = normals[tri].astype(np.float32) if normals is not None else None
        x_frac = (p[:, 0] - midx) / spanx
        y_frac = (p[:, 1] - miny) / spany
        if y_frac.max() < args.head_center - args.head_half_height or y_frac.min() > args.head_center + args.head_half_height:
            continue
        if x_frac.min() > args.head_half_width or x_frac.max() < -args.head_half_width:
            continue
        if n is None:
            face_n = np.cross(p[1] - p[0], p[2] - p[0])
            face_n /= max(np.linalg.norm(face_n), 1e-8)
            n = np.repeat(face_n[None], 3, axis=0)
        if front_sign * n[:, 2].max() < 0.10:
            continue

        t = uv_pixels[tri]
        x0, y0 = t[0]
        x1, y1 = t[1]
        x2, y2 = t[2]
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-8:
            continue
        xmin = max(0, int(np.floor(t[:, 0].min())))
        xmax = min(target_width - 1, int(np.ceil(t[:, 0].max())))
        ymin = max(0, int(np.floor(t[:, 1].min())))
        ymax = min(target_height - 1, int(np.ceil(t[:, 1].max())))
        if xmax < xmin or ymax < ymin:
            continue
        # Avoid pathological triangles that might cover almost the entire atlas.
        if (xmax - xmin + 1) * (ymax - ymin + 1) > 2_000_000:
            raise ValueError("UV triangle spans too much texture area for this pilot; lower atlas resolution")
        xx, yy = np.meshgrid(np.arange(xmin, xmax + 1), np.arange(ymin, ymax + 1))
        xx, yy = xx.ravel(), yy.ravel()
        a = ((y1 - y2) * (xx - x2) + (x2 - x1) * (yy - y2)) / denom
        b = ((y2 - y0) * (xx - x2) + (x0 - x2) * (yy - y2)) / denom
        c = 1.0 - a - b
        inside = (a >= -1e-5) & (b >= -1e-5) & (c >= -1e-5)
        if not np.any(inside):
            continue
        xx, yy, a, b, c = [v[inside] for v in (xx, yy, a, b, c)]
        xyz = a[:, None] * p[0] + b[:, None] * p[1] + c[:, None] * p[2]
        nxyz = a[:, None] * n[0] + b[:, None] * n[1] + c[:, None] * n[2]
        facing = front_sign * nxyz[:, 2] / np.maximum(np.linalg.norm(nxyz, axis=1), 1e-8)
        xf = (xyz[:, 0] - midx) / spanx
        yf = (xyz[:, 1] - miny) / spany
        head_mask = smooth01((yf - (args.head_center - args.head_half_height)) / (args.head_half_height * 0.34))
        head_mask *= smooth01(((args.head_center + args.head_half_height) - yf) / (args.head_half_height * 0.34))
        head_mask *= smooth01((args.head_half_width - np.abs(xf)) / (args.head_half_width * 0.38))
        head_mask *= smooth01((facing - 0.25) / 0.55)

        # Orthographic mapping of model X and height to the source character bbox.
        src_x = left + ((xyz[:, 0] - minx) / spanx) * (right - left)
        src_y = bottom - ((xyz[:, 1] - miny) / spany) * (bottom - top)
        within = (src_x >= 0) & (src_x < source_width - 1) & (src_y >= 0) & (src_y < source_height - 1)
        samples = bilinear_rgba(source, src_x, src_y)
        weight = args.strength * head_mask * (samples[:, 3] / 255.0)
        # Prefer the nearest front-facing vertex depths, where UVs are shared.
        sort_depth = front_sign * xyz[:, 2]
        valid = (weight > 0.005) & within & (sort_depth >= depth[yy, xx])
        if not np.any(valid):
            continue
        xx, yy = xx[valid], yy[valid]
        weight = weight[valid, None]
        sample = samples[valid, :3]
        out[yy, xx] = out[yy, xx] * (1 - weight) + sample * weight
        depth[yy, xx] = sort_depth[valid]
        contributions += int(len(xx))
        edited += 1

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB"), contributions, edited


def write_patched_glb(doc, binary, chunks, new_image, image_id, destination):
    # Append a new embedded image and update only the base-color image's bufferView.
    # The original is left in place to avoid offset changes to geometry, normals,
    # UVs, and other PBR images. Downstream export via Blender can repack it later.
    bio = io.BytesIO()
    new_image.save(bio, format="JPEG", quality=94, subsampling=0)
    payload = bio.getvalue()
    original_bytes = len(binary)
    pad = (-len(binary)) % 4
    binary += b"\x00" * pad
    start = len(binary)
    binary += payload
    binary += b"\x00" * ((-len(binary)) % 4)
    view_id = len(doc.setdefault("bufferViews", []))
    doc["bufferViews"].append({"buffer": 0, "byteOffset": start,
                               "byteLength": len(payload)})
    doc["images"][image_id]["bufferView"] = view_id
    doc["images"][image_id]["mimeType"] = "image/jpeg"
    doc["images"][image_id].pop("uri", None)
    doc["buffers"][0]["byteLength"] = len(binary)
    encoded_json = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    encoded_json += b" " * ((-len(encoded_json)) % 4)
    chunk_contents = [(JSON_CHUNK, encoded_json), (BIN_CHUNK, binary)]
    total_len = 12 + sum(8 + len(part) for _, part in chunk_contents)
    with destination.open("wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total_len))
        for kind, part in chunk_contents:
            f.write(struct.pack("<II", len(part), kind))
            f.write(part)
    print(f"Embedded new atlas: {len(payload) / 1024:.0f} KiB (original BIN: {original_bytes / 1024:.0f} KiB)")


def main():
    parser = argparse.ArgumentParser(description="Restore Mara's front facial colors from her cutout into a textured GLB")
    parser.add_argument("--mesh", type=Path, required=True, help="Paint3D's existing textured GLB")
    parser.add_argument("--image", type=Path, required=True, help="Original full-body transparent PNG")
    parser.add_argument("--output", type=Path, required=True, help="New corrected GLB (never overwrite input)")
    parser.add_argument("--strength", type=float, default=0.95, help="Front face color strength 0..1")
    parser.add_argument("--front", choices=["+z", "-z"], default="+z", help="Front of mesh in native glTF Y-up coordinates")
    parser.add_argument("--head-center", type=float, default=0.91, help="Face region vertical center, fraction of total height")
    parser.add_argument("--head-half-height", type=float, default=0.075, help="Face region half-height as fraction of body height")
    parser.add_argument("--head-half-width", type=float, default=0.12, help="Face region half-width as fraction of total body width")
    args = parser.parse_args()
    args.mesh = args.mesh.expanduser().resolve()
    args.image = args.image.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.mesh == args.output:
        parser.error("Output must differ from input; original GLB must be preserved")
    if not (0 <= args.strength <= 1):
        parser.error("--strength must be between 0 and 1")
    doc, binary, chunks = read_glb(args.mesh)
    meshes = doc.get("meshes", [])
    primitives = [p for m in meshes for p in m.get("primitives", [])]
    if len(primitives) != 1:
        raise ValueError("This pilot supports a GLB with exactly one mesh primitive")
    prim = primitives[0]
    attrs = prim["attributes"]
    for key in ["POSITION", "TEXCOORD_0"]:
        if key not in attrs:
            raise ValueError(f"Missing required attribute {key}")
    if "indices" not in prim:
        raise ValueError("This pilot expects indexed triangles")
    if prim.get("mode", 4) != 4:
        raise ValueError("This pilot supports triangles only")
    material_index = prim.get("material")
    if material_index is None:
        raise ValueError("Mesh has no material")
    material = doc["materials"][material_index]
    pbr = material.get("pbrMetallicRoughness", {})
    color = pbr.get("baseColorTexture")
    if color is None:
        raise ValueError("No base-color texture connected to the material")
    texture = doc["textures"][color["index"]]
    image_id = texture.get("source")
    if image_id is None:
        raise ValueError("Unsupported texture without a standard image source")
    positions = accessor_array(doc, binary, attrs["POSITION"])
    normals = accessor_array(doc, binary, attrs["NORMAL"]) if "NORMAL" in attrs else None
    uvs = accessor_array(doc, binary, attrs["TEXCOORD_0"])
    indices = accessor_array(doc, binary, prim["indices"]).reshape((-1, 3))
    base = extract_image(doc, binary, image_id)
    ref = Image.open(args.image).convert("RGBA")
    print(f"Mesh: {len(positions):,} vertices, {len(indices):,} triangles")
    print(f"Base atlas: {base.width} x {base.height}; reference: {ref.width} x {ref.height}")
    corrected, pixels, triangles = patch_atlas(base, ref, positions, normals, uvs, indices, args)
    if pixels < 40:
        raise RuntimeError(f"Only {pixels} UV texels changed. Try --front -z, or check character orientation/head position.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atlas = args.output.with_name(args.output.stem + "_face_atlas.jpg")
    corrected.save(atlas, "JPEG", quality=94, subsampling=0)
    write_patched_glb(doc, binary, chunks, corrected, image_id, args.output)
    print(f"Patched {pixels:,} atlas pixel hits across {triangles:,} face triangles")
    print(f"GLB: {args.output}")
    print(f"Preview atlas: {atlas}")
    print("This corrects only front facial colors. It cannot fix missing facial geometry or hidden side/back areas.")


if __name__ == "__main__":
    main()
