"""Dependency-free GLB metadata checks: no GPU, Blender, or model weights."""

import json
from pathlib import Path
import struct
import tempfile
import unittest

from ai3d.export.validation import readable_glb


def make_glb(path: Path, *, textured=False, indexed=True, mode=4, meshes=True):
    primitive = {"mode": mode, "attributes": {"POSITION": 0}}
    accessors = [{"count": 6}]
    if indexed:
        primitive["indices"] = 1
        accessors.append({"count": 6})
    if textured:
        primitive["attributes"]["TEXCOORD_0"] = 2
        primitive["material"] = 0
        accessors.append({"count": 6})
    document = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": [primitive]}] if meshes else [],
        "accessors": accessors,
    }
    if textured:
        document.update({
            "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
            "textures": [{"source": 0}],
            "images": [{"bufferView": 0, "mimeType": "image/png"}],
        })
    body = json.dumps(document).encode("utf-8")
    body += b" " * ((-len(body)) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(body)) +
                     struct.pack("<II", len(body), 0x4E4F534A) + body)


class GLBValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.glb = Path(self.temp.name) / "test.glb"

    def test_untextured_geometry_report_preserves_legacy_keys(self):
        make_glb(self.glb)
        report = readable_glb(self.glb)
        self.assertEqual(report["triangles"], 2)
        self.assertEqual(report["meshes"], 1)
        self.assertFalse(report["uv0"])
        self.assertEqual(report["images"], 0)
        self.assertEqual(set(report), {
            "file", "bytes", "meshes", "triangles", "materials",
            "textures", "images", "uv0", "base_color_primitives",
        })

    def test_textured_glb_passes_quality_gate(self):
        make_glb(self.glb, textured=True)
        report = readable_glb(self.glb, need_texture=True)
        self.assertTrue(report["uv0"])
        self.assertEqual(report["base_color_primitives"], 1)
        self.assertEqual(report["images"], 1)

    def test_untextured_glb_fails_texture_gate(self):
        make_glb(self.glb)
        with self.assertRaisesRegex(RuntimeError, "missing applied UV"):
            readable_glb(self.glb, need_texture=True)

    def test_nonindexed_triangle_primitive(self):
        make_glb(self.glb, indexed=False)
        self.assertEqual(readable_glb(self.glb)["triangles"], 2)

    def test_non_triangles_rejected(self):
        make_glb(self.glb, mode=1)
        with self.assertRaisesRegex(RuntimeError, "Non-triangle"):
            readable_glb(self.glb)

    def test_no_meshes_rejected(self):
        make_glb(self.glb, meshes=False)
        with self.assertRaisesRegex(RuntimeError, "no meshes"):
            readable_glb(self.glb)

    def test_missing_json_chunk_header_rejected(self):
        self.glb.write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
        with self.assertRaisesRegex(RuntimeError, "chunk header missing"):
            readable_glb(self.glb)

    def test_invalid_json_rejected(self):
        self.glb.write_bytes(struct.pack("<4sII", b"glTF", 2, 24) +
                             struct.pack("<II", 4, 0x4E4F534A) + b"nope")
        with self.assertRaisesRegex(RuntimeError, "Malformed GLB"):
            readable_glb(self.glb)

    def test_corrupt_glb_length_rejected(self):
        make_glb(self.glb)
        data = self.glb.read_bytes()
        self.glb.write_bytes(data[:8] + struct.pack("<I", len(data) + 1) + data[12:])
        with self.assertRaisesRegex(RuntimeError, "Invalid GLB v2 header"):
            readable_glb(self.glb)


if __name__ == "__main__":
    unittest.main()
