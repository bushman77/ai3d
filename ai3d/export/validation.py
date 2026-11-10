"""Fast, dependency-free structural checks for binary glTF 2.0 (GLB) assets.

This is not a renderer or a full glTF conformance validator. It checks enough
metadata to catch empty meshes and absent base-color textures before export.
"""

import json
from pathlib import Path
import struct

from ai3d.common import ensure_file

_JSON_CHUNK = 0x4E4F534A


def readable_glb(path: Path, need_texture: bool = False) -> dict:
    """Inspect a GLB and return the legacy pipeline's asset summary dictionary.

    Raises RuntimeError for invalid GLB structure or unmet mesh/texture checks.
    Preserves the existing summary keys for downstream report compatibility.
    """
    path = Path(path)
    ensure_file(path, "GLB")
    try:
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise RuntimeError(f"Truncated GLB: {path}")
            magic, version, total = struct.unpack("<4sII", header)
            if magic != b"glTF" or version != 2 or total != path.stat().st_size:
                raise RuntimeError(f"Invalid GLB v2 header: {path}")
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise RuntimeError(f"GLB JSON chunk header missing: {path}")
            size, kind = struct.unpack("<II", chunk_header)
            if kind != _JSON_CHUNK or size > total - 20:
                raise RuntimeError(f"Invalid GLB JSON chunk: {path}")
            raw = stream.read(size)
            if len(raw) != size:
                raise RuntimeError(f"Truncated GLB JSON chunk: {path}")
            doc = json.loads(raw)

        meshes = doc.get("meshes", [])
        if not meshes:
            raise RuntimeError(f"GLB has no meshes: {path}")
        triangles = 0
        has_uv = False
        textured_primitives = 0
        for mesh in meshes:
            for primitive in mesh.get("primitives", []):
                if primitive.get("mode", 4) != 4:
                    raise RuntimeError("Non-triangle glTF primitive detected; manual review required")
                accessor_index = primitive.get("indices")
                if accessor_index is None:
                    accessor_index = primitive["attributes"]["POSITION"]
                triangles += doc["accessors"][accessor_index]["count"] // 3
                has_uv = has_uv or "TEXCOORD_0" in primitive.get("attributes", {})
                material_index = primitive.get("material")
                materials = doc.get("materials", [])
                if material_index is not None and 0 <= material_index < len(materials):
                    pbr = materials[material_index].get("pbrMetallicRoughness", {})
                    if pbr.get("baseColorTexture") is not None:
                        textured_primitives += 1

        result = {
            "file": str(path),
            "bytes": path.stat().st_size,
            "meshes": len(meshes),
            "triangles": triangles,
            "materials": len(doc.get("materials", [])),
            "textures": len(doc.get("textures", [])),
            "images": len(doc.get("images", [])),
            "uv0": has_uv,
            "base_color_primitives": textured_primitives,
        }
        if triangles <= 0:
            raise RuntimeError(f"GLB has no triangles: {path}")
        if need_texture and not (has_uv and textured_primitives and result["images"]):
            raise RuntimeError(f"GLB is missing applied UV/base-color material/images: {path}")
        return result
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Malformed GLB structure: {path}: {exc}") from exc
