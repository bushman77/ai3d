import json
from pathlib import Path
import tempfile
import unittest

from ai3d.config import DEFAULT_PROFILE, REPO_ROOT, apply_override, load_profile, merge, repo_path


class ConfigTests(unittest.TestCase):
    def test_default_profile_loads_without_comment_keys(self):
        cfg = load_profile()
        self.assertNotIn("_about", cfg)
        self.assertNotIn("_about", cfg["shape"])
        for section in ("paths", "reference", "views", "shape", "paint_mesh", "paint",
                        "retopo", "rig", "report"):
            self.assertIn(section, cfg)

    def test_fast_profile_merges_over_default(self):
        cfg = load_profile(REPO_ROOT / "config" / "fast_6gb.json")
        self.assertEqual(cfg["paint"]["max_views"], 2)
        self.assertEqual(cfg["paint"]["category"], "humanoid")  # untouched default kept

    def test_set_override_parses_json_values(self):
        cfg = load_profile(overrides=["shape.steps=50", "rig.enabled=false",
                                      "paths.blender=/opt/blender/blender"])
        self.assertEqual(cfg["shape"]["steps"], 50)
        self.assertIs(cfg["rig"]["enabled"], False)
        self.assertEqual(cfg["paths"]["blender"], "/opt/blender/blender")

    def test_unknown_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown config key"):
            load_profile(overrides=["shape.stepz=50"])
        with self.assertRaisesRegex(ValueError, "Unknown config key"):
            merge({"a": 1}, {"b": 2})

    def test_bad_override_syntax(self):
        with self.assertRaisesRegex(ValueError, "section.key=value"):
            apply_override({"a": 1}, "a")

    def test_user_profile_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.json"
            path.write_text(json.dumps({"_note": "x", "seed": 7, "retopo": {"target_faces": 5000}}))
            cfg = load_profile(path)
            self.assertEqual(cfg["seed"], 7)
            self.assertEqual(cfg["retopo"]["target_faces"], 5000)

    def test_repo_path(self):
        self.assertEqual(repo_path("Hunyuan3D-2"), REPO_ROOT / "Hunyuan3D-2")
        self.assertEqual(repo_path("/abs/x"), Path("/abs/x"))
        self.assertEqual(repo_path("~/m"), Path.home() / "m")
        self.assertTrue(DEFAULT_PROFILE.is_file())


if __name__ == "__main__":
    unittest.main()
