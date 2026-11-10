"""Paint3D per-view and UV atlas diagnostic wiring (no GPU required)."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai3d.textures.diagnostics import (
    DEBUG_FILES, debug_directory, expected_debug_images, paint_debug_environment,
)
from pipelines.image_to_3d import arguments, main


class PaintDiagnosticsTests(unittest.TestCase):
    def test_cli_debug_is_disabled_by_default(self):
        self.assertFalse(arguments(["--name", "sample"]).paint_debug)

    def test_cli_can_enable_paint_debug(self):
        self.assertTrue(arguments(["--name", "sample", "--paint-debug"]).paint_debug)

    def test_debug_images_live_inside_output_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outputs" / "example_character"
            self.assertEqual(debug_directory(root), root / "paint_debug")
            self.assertEqual(
                expected_debug_images(root),
                [root / "paint_debug" / name for name in DEBUG_FILES],
            )
            self.assertFalse(root.exists())

    def test_enabled_environment_uses_selected_run(self):
        run = Path("/tmp/ai3d-outputs/test")
        original = {"PATH": "/usr/bin", "PAINT3D_DEBUG_DIR": "/tmp/old"}
        result = paint_debug_environment(original, run, enabled=True)
        self.assertEqual(result["PAINT3D_DEBUG_DIR"], "/tmp/ai3d-outputs/test/paint_debug")
        self.assertEqual(original["PAINT3D_DEBUG_DIR"], "/tmp/old")

    def test_disabled_debug_cannot_leak_to_old_directory(self):
        original = {"PAINT3D_DEBUG_DIR": "/tmp/old", "PATH": "/usr/bin"}
        result = paint_debug_environment(original, Path("/tmp/run"))
        self.assertNotIn("PAINT3D_DEBUG_DIR", result)
        self.assertEqual(result["PATH"], "/usr/bin")

    def test_debug_painted_mesh_skip_rejected(self):
        options = arguments([
            "--name", "test", "--paint-debug", "--painted-mesh", "/tmp/painted.glb",
        ])
        with patch("pipelines.image_to_3d.arguments", return_value=options):
            with self.assertRaisesRegex(RuntimeError, "skips painting"):
                main()

    def test_expected_core_debug_images_exist_in_manifest(self):
        self.assertIn("tex_baked.png", DEBUG_FILES)
        self.assertIn("tex_trust.png", DEBUG_FILES)
        self.assertIn("tex_inpainted.png", DEBUG_FILES)


if __name__ == "__main__":
    unittest.main()
