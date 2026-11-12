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
            "upper_outfit": [[-0.5, -0.2, -0.5], [0.5, 0.2, 0.5]],
            "lower_outfit": [[-0.5, -0.2, -0.6], [0.5, 0.2, 0.6]],
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

    def world_box(self, part_id, fitted=None):
        part = next(p for p in (fitted or self.load())["parts"] if p["id"] == part_id)
        lo, hi = self.bounds[part_id]
        offset = part["transform"]["position"]
        scale = part["transform"]["scale"]
        return (
            [lo[i] * scale[i] + offset[i] for i in range(3)],
            [hi[i] * scale[i] + offset[i] for i in range(3)],
        )

    def test_landmark_fit_keeps_trousers_below_waist_and_jacket_below_neck(self):
        self.assertTrue(fit_manifest(self.manifest, self.measurements))
        result = self.load()
        parts = {p["id"]: p for p in result["parts"]}
        self.assertEqual(result["auto_fit"]["version"], 3)
        self.assertEqual(parts["head"]["transform"]["scale"], [0.4] * 3)
        self.assertEqual(parts["head"]["transform"]["position"][2], 0.8)
        self.assertAlmostEqual(parts["body"]["cut"]["plane_z"], 0.66)

        upper_lo, upper_hi = self.world_box("upper_outfit", result)
        lower_lo, lower_hi = self.world_box("lower_outfit", result)
        self.assertAlmostEqual(upper_lo[2], 0.08, places=5)
        self.assertAlmostEqual(upper_hi[2], 0.80, places=5)
        self.assertAlmostEqual(lower_lo[2], -0.96, places=5)
        self.assertAlmostEqual(lower_hi[2], 0.12, places=5)
        # This is the regression for the screenshot's pants-over-the-head.
        self.assertLess(lower_hi[2], parts["body"]["cut"]["plane_z"])
        self.assertLessEqual(lower_hi[0] - lower_lo[0], 0.68 + 1e-5)
        self.assertEqual(parts["upper_outfit"]["status"], "landmark_box_fit_unverified")
        self.assertEqual(parts["lower_outfit"]["status"], "landmark_box_fit_unverified")
        self.assertEqual(parts["equipment"]["status"], "belt_and_pouches_fit_unverified")
        self.assertFalse(parts["equipment"]["visible"])

    def test_glove_pair_receives_distinct_wrist_anchors_not_torso_scale(self):
        fit_manifest(self.manifest, self.measurements)
        result = self.load()
        hands = next(p for p in result["parts"] if p["id"] == "hands")
        layout = hands["pair_layout"]
        self.assertEqual(layout["mode"], "split_x_to_wrists_v1")
        self.assertEqual(hands["status"], "glove_pair_split_planned")
        self.assertEqual(hands["transform"]["scale"], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(layout["left_wrist"][0], -0.72)
        self.assertAlmostEqual(layout["right_wrist"][0], 0.72)
        self.assertAlmostEqual(layout["left_wrist"][2], 0.10)
        self.assertAlmostEqual(layout["hand_length"], 0.24)
        self.assertAlmostEqual(layout["hand_width"], 0.18)
        self.assertNotEqual(layout["left_wrist"], layout["right_wrist"])

    def test_legacy_hair_remains_optional_and_no_second_head_is_required(self):
        fit_manifest(self.manifest, self.measurements)
        result = self.load()
        parts = {p["id"]: p for p in result["parts"]}
        self.assertEqual(parts["hair"]["status"], "heuristic_fit_unverified")
        self.assertIn("head", parts)

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
