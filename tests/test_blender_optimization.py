"""No-GPU tests for the extracted Blender static-GLB optimizer."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ai3d.optimization.blender import build_finalize_command
from ai3d.optimization.blender_finalize import parse_arguments, tris


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / "ai3d/optimization/blender_finalize.py"
COMPAT = ROOT / "space_nova_pipeline/space_nova_blender_finalize.py"


class BlenderOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.glb"
        self.source.write_bytes(b"not a real GLB; argument parsing only")
        self.target = Path(self.temp.name) / "out.glb"

    def test_builds_compatible_blender_command(self):
        command = build_finalize_command(
            "blender", COMPAT, self.source, self.target, 15000
        )
        self.assertEqual(command, [
            "blender", "--background", "--factory-startup", "--python-exit-code",
            "1", "--python", str(COMPAT), "--", "--input", str(self.source),
            "--output", str(self.target), "--target-faces", "15000",
        ])

    def test_rejects_same_source_and_destination(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            build_finalize_command("blender", COMPAT, self.source, self.source)

    def test_rejects_invalid_triangle_target(self):
        with self.assertRaisesRegex(ValueError, ">= 100"):
            build_finalize_command("blender", COMPAT, self.source, self.target, 99)

    def test_parses_valid_arguments_without_bpy_installed(self):
        options, source, target = parse_arguments([
            "--input", str(self.source), "--output", str(self.target),
            "--target-faces", "5000",
        ])
        self.assertEqual(options.target_faces, 5000)
        self.assertEqual(source, self.source)
        self.assertEqual(target, self.target)

    def test_rejects_same_paths_at_script_boundary(self):
        with self.assertRaises(SystemExit) as error:
            parse_arguments(["--input", str(self.source), "--output", str(self.source)])
        self.assertEqual(error.exception.code, 2)

    def test_rejects_missing_source_at_script_boundary(self):
        with self.assertRaises(SystemExit) as error:
            parse_arguments(["--input", str(self.target), "--output", str(self.source)])
        self.assertEqual(error.exception.code, 2)

    def test_triangle_counter(self):
        class Polygon:
            def __init__(self, n):
                self.vertices = range(n)

        class Object:
            class Data:
                polygons = [Polygon(3), Polygon(4), Polygon(2)]
            data = Data()

        self.assertEqual(tris(Object()), 3)

    def test_legacy_entry_point_runs_new_argument_validation(self):
        command = [sys.executable, str(COMPAT), "--",
                   "--input", str(self.target), "--output", str(self.source)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Source missing:", result.stderr)
        self.assertNotIn("No module named 'bpy'", result.stderr)

    def test_generic_finalizer_runs_argument_validation(self):
        command = [sys.executable, str(FINALIZER), "--",
                   "--input", str(self.target), "--output", str(self.source)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Source missing:", result.stderr)


if __name__ == "__main__":
    unittest.main()
