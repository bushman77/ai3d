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
        self.assertIn("upper_outfit", result)
        self.assertIn("lower_outfit", result)
        self.assertIn("not conditioned on a master PNG", result)

    def test_each_stage_has_component_selection_and_dry_run(self):
        for stage, part in [
            ("reference", "body"),
            ("reference", "head"),
            ("reference", "upper_outfit"),
            ("reference", "lower_outfit"),
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
        out = self.command("--stage", "shape", "--part", "upper_outfit", "--dry-run", ok=False)
        self.assertIn("region, not a fitted mesh", out)
        out = self.command("--stage", "shape", "--part", "upper_outfit",
                           "--experimental-region-mesh", "--dry-run")
        self.assertIn("upper_outfit", out)

    def test_outfit_references_alias_generates_exactly_two_reference_jobs(self):
        out = self.command("--outfit-references", "--prefix", "mara_clean_v2", "--dry-run")
        self.assertIn("Selected parts: 2", out)
        self.assertIn("mara_clean_v2_upper_outfit_upper_outfit_closeup", out)
        self.assertIn("mara_clean_v2_lower_outfit_lower_outfit_closeup", out)
        self.assertNotIn("mara_clean_v2_head_head_closeup", out)
        self.assertNotIn("mara_clean_v2_body_front", out)
        self.assertIn("cannot be combined",
                      self.command("--outfit-references", "--stage", "paint",
                                   "--dry-run", ok=False))
        self.assertIn("cannot be combined",
                      self.command("--outfit-references", "--part", "head",
                                   "--dry-run", ok=False))

    def test_prototype_all_parts_dry_run_attempts_every_3d_region(self):
        out = self.command("--prototype-all-parts", "--prefix", "mara_proof", "--dry-run")
        for ident in ("body", "head", "upper_outfit",
                      "lower_outfit", "hands", "equipment"):
            self.assertIn(f"[COMPONENT", out)
            self.assertIn(f"mara_proof_{ident}_", out)
        # All six parts must reach Paint3D (including reference-only regions).
        self.assertEqual(out.count("requested target: paint"), 6)
        self.assertEqual(out.count("Dry run: would invoke ai3d generate"), 6)
        self.assertNotIn("Region parts produce references only", out)
        self.assertEqual(out.count("[DRY RUN] Would render:"), 6)
        self.assertIn("prototype_gallery", out)
        self.assertIn("STANDALONE 3D PROTOTYPES", out)

    def test_removed_hair_component_cannot_be_generated(self):
        out = self.command("--prototype-all-parts", "--part", "hair",
                           "--dry-run", ok=False)
        self.assertIn("Unknown part", out)
        out = self.command("--prototype-all-parts", "--dry-run")
        self.assertNotIn("mara_complete_v1_hair_", out)
        self.assertIn("mara_complete_v1_head_head_closeup", out)

    def test_prototype_render_only_dry_run_never_infers(self):
        out = self.command("--prototype-all-parts", "--render-only",
                           "--part", "upper_outfit", "--prefix", "mara_proof", "--dry-run")
        self.assertIn("Reusing existing mesh", out)
        self.assertNotIn("would invoke ai3d generate", out)
        self.assertEqual(out.count("[DRY RUN] Would render:"), 1)

    def test_prototype_rejects_conflicting_modes_and_bad_part(self):
        self.assertIn("cannot be combined",
                      self.command("--prototype-all-parts", "--stage", "paint",
                                   "--dry-run", ok=False))
        self.assertIn("Unknown part",
                      self.command("--prototype-all-parts", "--part", "tail",
                                   "--dry-run", ok=False))
        self.assertIn("requires --prototype-all-parts",
                      self.command("--render-only", "--dry-run", ok=False))

    def test_prototype_render_only_with_fake_blender_produces_gallery(self):
        import json
        fake = Path(self.temp.name) / "fake-blender"
        # The fake stands in for Blender: no graphics or AI inference runs.
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib,sys\n"
            "a=sys.argv; d=pathlib.Path(a[a.index('--output-dir')+1])\n"
            "for v in ('front','side','back','threequarter'):\n"
            "    (d/('preview_'+v+'.png')).write_bytes(b'fake-png')\n"
        )
        fake.chmod(0o755)
        card = json.loads((ROOT / "examples/space_nova/characters/mara_venn.json").read_text())
        part = next(p for p in card["parts"] if p["id"] == "upper_outfit")
        folder = self.output / f"mara_proof_upper_outfit_{part['reference_view']}"
        folder.mkdir(parents=True)
        mesh = folder / "05_painted.glb"
        mesh.write_bytes(b"mock-glb")
        result = subprocess.run(
            ["bash", str(SCRIPT), "--output-dir", str(self.output),
             "--prototype-all-parts", "--render-only", "--part", "upper_outfit",
             "--prefix", "mara_proof"],
            cwd=ROOT, env={**__import__("os").environ, "BLENDER": str(fake)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(mesh.read_bytes(), b"mock-glb")
        html = (self.output / "mara_proof_prototypes/index.html").read_text()
        self.assertIn("upper_outfit", html)
        self.assertIn("preview_front.png", html)
        self.assertIn("05_painted.glb", html)
        self.assertNotIn("head ·", html)

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
