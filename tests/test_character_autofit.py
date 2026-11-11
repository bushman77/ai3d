"""Pure-Python bounds fitting tests; Blender and CUDA not required."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai3d.characters.autofit import fit_manifest


class AutoFitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.manifest = root / "assembly.json"
        self.measurements = root / "measurements.json"
        parts = []
        measures = []
        self.bounds = {
            "body": [[-0.8, -0.3, -1.0], [0.8, 0.3, 1.0]],
            "head": [[-0.4, -0.4, -0.5], [0.4, 0.4, 0.5]],
            "hair": [[-0.2, -0.2, -0.3], [0.2, 0.2, 0.3]],
            "outfit": [[-0.5, -0.2, -0.6], [0.5, 0.2, 0.6]],
            "hands": [[-0.6, -0.2, -0.2], [0.6, 0.2, 0.2]],
            "equipment": [[-0.5, -0.1, -0.1], [0.5, 0.1, 0.1]],
        }
        for ident, (lo, hi) in self.bounds.items():
            source = root / f"{ident}.glb"
            source.write_bytes(b"nonempty test fixture")
            parts.append({
                "id": ident, "source": str(source),
                "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0],
                              "scale": [1, 1, 1]},
                "visible": ident in ("body", "head"),
                "include_in_preview": ident in ("body", "head"),
            })
            measures.append({"id": ident, "bounds_with_user_transform": {
                "min": lo, "max": hi,
                "center": [(a + b) / 2 for a, b in zip(lo, hi)],
                "size": [b - a for a, b in zip(lo, hi)],
            }})
        self.manifest.write_text(json.dumps({
            "manifest_version": 1, "character_id": "test_character",
            "parts": parts, "preview_layout": "overlay",
        }))
        self.measurements.write_text(json.dumps({
            "character_id": "test_character", "components": measures,
        }))

    def load(self):
        return json.loads(self.manifest.read_text())

    def test_fit_includes_head_and_equipment_but_stages_regions(self):
        self.assertTrue(fit_manifest(self.manifest, self.measurements))
        result = self.load()
        parts = {p["id"]: p for p in result["parts"]}
        self.assertEqual(parts["head"]["transform"]["scale"], [0.4] * 3)
        self.assertEqual(parts["head"]["transform"]["position"][2], 0.8)
        self.assertAlmostEqual(parts["body"]["cut"]["plane_z"], 0.66)
        self.assertTrue(parts["equipment"]["include_in_preview"])
        for ident in ("hair", "hands", "outfit"):
            self.assertFalse(parts[ident]["include_in_preview"])
            self.assertEqual(parts[ident]["status"], "staged_for_manual_replacement")

    def test_preserves_manual_tweaks_without_refit(self):
        fit_manifest(self.manifest, self.measurements)
        result = self.load()
        head = next(p for p in result["parts"] if p["id"] == "head")
        head["transform"]["position"][0] = 0.04
        self.manifest.write_text(json.dumps(result))
        self.assertFalse(fit_manifest(self.manifest, self.measurements))
        self.assertEqual(next(p for p in self.load()["parts"]
                              if p["id"] == "head")["transform"]["position"][0], 0.04)

    def test_mismatched_measurements_fail_without_changes(self):
        report = json.loads(self.measurements.read_text())
        report["character_id"] = "other"
        self.measurements.write_text(json.dumps(report))
        before = self.manifest.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "do not match"):
            fit_manifest(self.manifest, self.measurements)
        self.assertEqual(self.manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
