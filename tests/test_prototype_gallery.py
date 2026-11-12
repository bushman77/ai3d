"""Offline regressions for the all-parts Blender render/gallery flow."""
from contextlib import redirect_stdout
import ast
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai3d.characters.card import ROOT, load_card
from ai3d.characters.prototype_gallery import (
    VIEWS, create_gallery, prototype_paths,
)

MARA = ROOT / "examples/space_nova/characters/mara_venn.json"


class PrototypeGalleryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.outputs = Path(self.temp.name) / "outputs"
        self.card = load_card(MARA)
        self.prefix = "mara_prototype_test"

    def test_renderer_has_valid_syntax_and_three_views(self):
        path = ROOT / "ai3d/characters/blender_render_component.py"
        ast.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(VIEWS, ("front", "threequarter", "side"))
        self.assertIn("bpy.ops.import_scene.gltf", path.read_text(encoding="utf-8"))

    def test_paths_cover_all_parts_in_card_order(self):
        paths = list(prototype_paths(self.card, self.prefix, self.outputs))
        self.assertEqual([entry["id"] for entry in paths],
                         [p["id"] for p in self.card["parts"]])
        self.assertEqual(len(paths), 7)
        self.assertEqual(len({str(p["glb"]) for p in paths}), 7)
        for entry in paths:
            self.assertEqual(entry["glb"].name, "06_game.glb")
            self.assertEqual(len(entry["previews"]), 3)

    def test_dry_run_writes_nothing_and_does_not_call_blender(self):
        with patch("ai3d.characters.prototype_gallery.subprocess.run") as run:
            with redirect_stdout(io.StringIO()) as stdout:
                result = create_gallery(self.card, self.prefix, self.outputs,
                                        blender="fake-blender", dry_run=True)
        run.assert_not_called()
        self.assertFalse(self.outputs.exists())
        self.assertEqual(result.name, "index.html")
        self.assertIn("hair:", stdout.getvalue())
        self.assertIn("upper_outfit:", stdout.getvalue())
        self.assertIn("lower_outfit:", stdout.getvalue())

    def test_missing_geometry_fails_without_claiming_success(self):
        with self.assertRaisesRegex(RuntimeError, "no game-stage GLB"):
            create_gallery(self.card, self.prefix, self.outputs,
                           blender="fake-blender")

    def test_separate_rendered_parts_get_html_gallery_and_resume(self):
        paths = list(prototype_paths(self.card, self.prefix, self.outputs))
        for entry in paths:
            entry["folder"].mkdir(parents=True)
            for name in ("01_reference.png", "03_shape.glb",
                         "05_painted.glb", "06_game.glb"):
                (entry["folder"] / name).write_bytes(b"test")
        calls = []

        def fake_blender(cmd, check=False):
            self.assertTrue(check)
            self.assertIn("--background", cmd)
            self.assertIn("--factory-startup", cmd)
            self.assertIn("--python-exit-code", cmd)
            mesh = Path(cmd[cmd.index("--input") + 1])
            calls.append(mesh)
            for view in VIEWS:
                (mesh.parent / f"07_preview_{view}.png").write_bytes(b"fake-png")
            return None

        with patch("ai3d.characters.prototype_gallery.subprocess.run",
                   side_effect=fake_blender) as run:
            with redirect_stdout(io.StringIO()):
                index = create_gallery(self.card, self.prefix, self.outputs,
                                       blender="fake-blender")
            self.assertEqual(run.call_count, 7)
            self.assertEqual(calls, [p["glb"] for p in paths])
            html = index.read_text(encoding="utf-8")
            self.assertEqual(html.count("<section>"), 7)
            self.assertEqual(html.count("<img "), 21)
            self.assertIn("upper_outfit", html)
            self.assertIn("lower_outfit", html)
            self.assertIn("07_preview_threequarter.png", html)
            report = json.loads((index.parent / "report.json").read_text())
            self.assertEqual(len(report["parts"]), 7)
            with redirect_stdout(io.StringIO()):
                create_gallery(self.card, self.prefix, self.outputs,
                               blender="fake-blender")
            self.assertEqual(run.call_count, 7, "Resume should reuse previews")


if __name__ == "__main__":
    unittest.main()
