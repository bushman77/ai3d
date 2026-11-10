"""Regressions for the standalone project-neutral AI3D CLI.

Tests use only the Python standard library and never launch AI inference.
"""

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from pipelines.image_to_3d import arguments as generic_arguments
from space_nova_pipeline.space_nova_pipeline import arguments as legacy_arguments

REPO = Path(__file__).resolve().parents[1]
LEGACY = REPO / "space_nova_pipeline/space_nova_pipeline.py"


def tiny_glb(path: Path) -> None:
    document = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": [{
            "mode": 4, "attributes": {"POSITION": 0}, "indices": 1,
        }]}],
        "accessors": [{"count": 3}, {"count": 3}],
    }
    encoded = json.dumps(document).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(encoded)) +
        struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    )


class StandaloneCLITests(unittest.TestCase):
    def run_ai3d(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "ai3d", *args],
            cwd=REPO, capture_output=True, text=True, check=False,
        )

    def test_top_level_help(self):
        result = self.run_ai3d("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("generate", result.stdout)
        self.assertIn("inspect", result.stdout)
        self.assertNotIn("Space Nova", result.stdout)

    def test_no_args_shows_help_without_error(self):
        result = self.run_ai3d()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("generate", result.stdout)

    def test_generate_help_is_generic(self):
        result = self.run_ai3d("generate", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AI3D asset pipeline", result.stdout)
        self.assertIn("--output-dir", result.stdout)
        self.assertNotIn("Space Nova", result.stdout)

    def test_inspect_help(self):
        result = self.run_ai3d("inspect", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--require-texture", result.stdout)

    def test_inspect_reads_glb_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mesh.glb"
            tiny_glb(path)
            result = self.run_ai3d("inspect", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(result.stdout)
            self.assertEqual(info["triangles"], 1)
            self.assertEqual(info["meshes"], 1)

    def test_inspect_texture_gate_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mesh.glb"
            tiny_glb(path)
            result = self.run_ai3d("inspect", str(path), "--require-texture")
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing applied UV", result.stderr)

    def test_generate_reference_stage_only_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            reference = folder / "ref.png"
            reference.write_bytes(b"reference copied without decoding")
            output = folder / "outputs"
            result = self.run_ai3d(
                "generate", "--name", "sample",
                "--image", str(reference),
                "--output-dir", str(output),
                "--stop-after", "reference",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((output / "sample/01_reference.png").read_bytes(),
                             reference.read_bytes())
            self.assertTrue((output / "sample/.stages/reference.json").exists())

    def test_legacy_cli_still_runs_reference_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            reference = folder / "ref.png"
            reference.write_bytes(b"compatibility copy only")
            output = folder / "outputs"
            result = subprocess.run(
                [sys.executable, str(LEGACY), "--name", "legacy",
                 "--image", str(reference), "--output-dir", str(output),
                 "--stop-after", "reference"],
                cwd=tmp, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((output / "legacy/01_reference.png").read_bytes(),
                             reference.read_bytes())

    def test_legacy_import_preserves_arguments(self):
        self.assertEqual(legacy_arguments(["--name", "sample"]).name, "sample")
        self.assertEqual(generic_arguments(["--name", "sample"]).name, "sample")

    def test_unknown_command_reports_usage(self):
        result = self.run_ai3d("missing-command")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
