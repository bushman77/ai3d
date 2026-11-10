"""Single-output-root contract for the legacy pipeline and reusable AI3D."""

import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory
from space_nova_pipeline.space_nova_pipeline import arguments


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ENTRY = REPO_ROOT / "space_nova_pipeline" / "space_nova_pipeline.py"


class OutputDirectoryTests(unittest.TestCase):
    def test_default_is_repository_outputs(self):
        self.assertEqual(DEFAULT_OUTPUT_ROOT, REPO_ROOT / "outputs")
        self.assertEqual(run_directory("sample"), REPO_ROOT / "outputs" / "sample")

    def test_default_cli_uses_outputs_not_pipeline_runs(self):
        args = arguments(["--name", "sample"])
        self.assertEqual(args.workdir, REPO_ROOT / "outputs")
        self.assertEqual(run_directory(args.name, args.workdir), REPO_ROOT / "outputs" / "sample")

    def test_output_dir_override(self):
        args = arguments(["--name", "sample", "--output-dir", "/tmp/other-ai3d"])
        self.assertEqual(run_directory(args.name, args.workdir), Path("/tmp/other-ai3d/sample"))

    def test_legacy_workdir_alias_still_supported(self):
        args = arguments(["--name", "sample", "--workdir", "/tmp/legacy-ai3d"])
        self.assertEqual(run_directory(args.name, args.workdir), Path("/tmp/legacy-ai3d/sample"))

    def test_asset_name_cannot_traverse_outside_output(self):
        for name in ("..", "../escape", "bad/name", "."):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                run_directory(name)

    def test_dry_run_does_not_create_any_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "reference.png"
            image.write_bytes(b"placeholder image for the reference-copy stage")
            output_root = Path(tmp) / "outputs"
            completed = subprocess.run(
                [sys.executable, str(LEGACY_ENTRY), "--name", "test_asset",
                 "--image", str(image), "--stop-after", "reference",
                 "--output-dir", str(output_root), "--dry-run"],
                cwd=tmp, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(str(output_root / "test_asset"), completed.stdout)
            self.assertFalse(output_root.exists())

    def test_reference_only_run_writes_under_single_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "reference.png"
            image.write_bytes(b"placeholder image for the reference-copy stage")
            output_root = Path(tmp) / "outputs"
            completed = subprocess.run(
                [sys.executable, str(LEGACY_ENTRY), "--name", "test_asset",
                 "--image", str(image), "--stop-after", "reference",
                 "--output-dir", str(output_root)],
                cwd=tmp, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            folder = output_root / "test_asset"
            self.assertEqual((folder / "01_reference.png").read_bytes(), image.read_bytes())
            self.assertTrue((folder / ".stages/reference.json").exists())
            self.assertTrue((folder / "logs").is_dir())
            self.assertFalse((Path(tmp) / "pipeline_runs").exists())
            self.assertFalse((Path(tmp) / "assets").exists())


if __name__ == "__main__":
    unittest.main()
