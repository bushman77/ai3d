"""Shell orchestrator regression tests: no GPU, Blender, or external model files."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_character.sh"


class ModularShellTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "generated"

    def command(self, *args, ok=True):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--output-dir", str(self.output), *args],
            cwd=ROOT, capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout[-800:])
        else:
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists(), "Dry run or plan wrote generated artifacts")
        return result.stdout + result.stderr

    def test_default_is_readonly_plan(self):
        result = self.command("--prefix", "modular_smoke")
        self.assertIn("[MODULAR PLAN]", result)
        self.assertIn("body", result)
        self.assertIn("head", result)
        self.assertIn("outfit", result)
        self.assertIn("not conditioned on a master PNG", result)

    def test_each_stage_has_component_selection_and_dry_run(self):
        for stage, part in [
            ("reference", "body"),
            ("reference", "head"),
            ("reference", "outfit"),
            ("shape", "head"),
            ("shape", "body"),
            ("paint", "head"),
            ("game", "body"),
        ]:
            with self.subTest(stage=stage, part=part):
                out = self.command("--stage", stage, "--part", part, "--prefix", "staged_smoke", "--dry-run")
                self.assertIn("Dry run", out)

    def test_reference_batch_is_explicit_and_readonly(self):
        output = self.command("--stage", "reference", "--all-parts",
                              "--prefix", "batch_smoke", "--dry-run")
        self.assertIn("Selected parts: 6", output)
        self.assertIn("equipment", output)

    def test_region_mesh_requires_experimental_flag(self):
        out = self.command("--stage", "shape", "--part", "outfit", "--dry-run", ok=False)
        self.assertIn("region, not a fitted mesh", out)
        out = self.command("--stage", "shape", "--part", "outfit",
                           "--experimental-region-mesh", "--dry-run")
        self.assertIn("outfit", out)

    def test_preview_must_be_chosen_and_never_runs_with_dry_run(self):
        out = self.command("--stage", "preview", "--prefix", "preview_smoke", "--dry-run")
        self.assertIn("body+head preview", out)

    def test_invalid_stage_and_unsafe_all_meshes_fail(self):
        self.assertIn("Unknown modular stage", self.command("--stage", "nonsense", ok=False))
        self.assertIn("only for reference", self.command("--stage", "game", "--all-parts", ok=False))
        self.assertIn("Specify --part", self.command("--stage", "shape", ok=False))
        self.assertIn("either --all-parts or --part",
                      self.command("--stage", "reference", "--all-parts",
                                   "--part", "head", ok=False))

    def test_body_only_alias_and_legacy_mode_plan(self):
        result = self.command("--body-only", "--prefix", "body_smoke", "--dry-run")
        self.assertIn("[MODULAR shape]", result)
        self.assertIn("body", result)
        self.assertIn("cannot be combined with --stage",
                      self.command("--body-only", "--stage", "shape", "--dry-run", ok=False))


if __name__ == "__main__":
    unittest.main()
