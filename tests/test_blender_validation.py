"""Blender round-trip workflow tests without requiring Blender or model weights.

The command subprocess is mocked; a real Blender import/export must still be
verified on a machine that has Blender and a textured GLB installed.
"""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch
import struct
import subprocess
import sys
import tempfile
import unittest

from ai3d.blender_validation import parse_and_validate, validate_blender, sha256_file

REPO = Path(__file__).resolve().parents[1]


def make_glb(path: Path, *, textured: bool = True, triangles: int = 100) -> None:
    primitive = {
        "mode": 4,
        "attributes": {"POSITION": 0},
        "indices": 1,
    }
    doc = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": [primitive]}],
        "accessors": [{"count": 3 * triangles}, {"count": 3 * triangles}],
    }
    if textured:
        primitive["attributes"]["TEXCOORD_0"] = 2
        primitive["material"] = 0
        doc["accessors"].append({"count": 3 * triangles})
        doc["materials"] = [
            {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
        ]
        doc["textures"] = [{"source": 0}]
        doc["images"] = [{"bufferView": 0, "mimeType": "image/png"}]
    encoded = json.dumps(doc).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(encoded)) +
        struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    )


class BlenderValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "textured.glb"
        make_glb(self.source, triangles=1000)
        self.root_output = self.root / "outputs"

    def test_dry_run_is_read_only_and_does_not_require_blender(self):
        with redirect_stdout(StringIO()) as captured:
            result = validate_blender(
                self.source, name="probe", target_faces=500,
                blender="/nonexistent/blender", output_dir=self.root_output,
                dry_run=True,
            )
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(self.root_output.exists())
        self.assertIn("--target-faces 500", captured.getvalue())

    def test_default_name_rejects_traversal(self):
        with self.assertRaisesRegex(RuntimeError, "name"):
            validate_blender(self.source, name="../escape",
                             output_dir=self.root_output, dry_run=True)

    def test_rejects_untextured_source_without_creating_output(self):
        make_glb(self.source, textured=False)
        with self.assertRaisesRegex(RuntimeError, "missing applied UV"):
            validate_blender(self.source, name="test", output_dir=self.root_output,
                             dry_run=True)
        self.assertFalse(self.root_output.exists())

    def test_rejects_bad_target(self):
        with self.assertRaisesRegex(ValueError, ">= 100"):
            validate_blender(self.source, name="test", target_faces=0, dry_run=True)

    def test_rejects_existing_output_directory(self):
        folder = self.root_output / "test"
        folder.mkdir(parents=True)
        (folder / "precious.txt").write_text("do not overwrite")
        with self.assertRaisesRegex(RuntimeError, "not empty"):
            validate_blender(self.source, name="test", output_dir=self.root_output,
                             dry_run=True)
        self.assertEqual((folder / "precious.txt").read_text(), "do not overwrite")

    def test_rejects_missing_blender_before_creating_output(self):
        with patch("ai3d.blender_validation.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "executable not found"):
                validate_blender(self.source, name="test", output_dir=self.root_output)
        self.assertFalse(self.root_output.exists())

    def test_mocked_round_trip_writes_report_and_preserves_source(self):
        original_hash = sha256_file(self.source)

        def fake_blender(_runner, _label, command):
            # Synthetic structural output: validates orchestration only.
            dest = Path(command[command.index("--output") + 1])
            make_glb(dest, triangles=450)

        with patch("ai3d.blender_validation.shutil.which", return_value="/usr/bin/blender"):
            with patch("ai3d.blender_validation.Runner.command", autospec=True,
                       side_effect=fake_blender):
                with redirect_stdout(StringIO()):
                    report = validate_blender(
                        self.source, name="test", target_faces=500,
                        output_dir=self.root_output,
                    )
        self.assertEqual(report["status"], "structural_pass")
        self.assertEqual(report["source"]["triangles"], 1000)
        self.assertEqual(report["output"]["triangles"], 450)
        self.assertTrue(report["manual_visual_review_required"])
        self.assertEqual(sha256_file(self.source), original_hash)
        self.assertTrue((self.root_output / "test/blender_validated.glb").exists())
        persisted = json.loads((self.root_output / "test/blender_validation.json").read_text())
        self.assertEqual(persisted["source_sha256"], original_hash)

    def test_rejects_triangle_count_increase_with_report(self):
        def fake_blender(_runner, _label, command):
            dest = Path(command[command.index("--output") + 1])
            make_glb(dest, triangles=1500)

        with patch("ai3d.blender_validation.shutil.which", return_value="/bin/blender"):
            with patch("ai3d.blender_validation.Runner.command", autospec=True,
                       side_effect=fake_blender):
                with redirect_stdout(StringIO()):
                    with self.assertRaisesRegex(RuntimeError, "structural validation failed"):
                        validate_blender(self.source, name="test", target_faces=500,
                                         output_dir=self.root_output)
        persisted = json.loads((self.root_output / "test/blender_validation.json").read_text())
        self.assertFalse(persisted["checks"]["triangle_count_not_increased"])
        self.assertEqual(persisted["status"], "structural_fail")

    def test_parse_supports_dry_run(self):
        with redirect_stdout(StringIO()):
            result = parse_and_validate([
                str(self.source), "--name", "probe",
                "--output-dir", str(self.root_output), "--dry-run",
            ])
        self.assertEqual(result["status"], "dry_run")

    def test_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "validate-blender", "--help"],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--target-faces", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    def test_root_help_exposes_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "--help"],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validate-blender", result.stdout)


if __name__ == "__main__":
    unittest.main()
