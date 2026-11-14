"""Regression tests for the first, skeleton-only AI3D rigging milestone.

No Hunyuan, Blender, model downloads, or image generation required in CI.
"""
from pathlib import Path
import json
import math
import os
import subprocess
import tempfile
import unittest

from ai3d.characters.card import ROOT, load_card
from ai3d.rigging.landmarks import humanoid_bones
from ai3d.rigging.prototype import build, options, plan_paths


CARD = ROOT / "examples/space_nova/characters/mara_venn.json"


class SkeletonLandmarksTest(unittest.TestCase):
    def test_humanoid_estimated_bones_are_parented_and_mirrored(self):
        body = {"min": [-0.55, -0.2, 0], "max": [0.55, 0.2, 1.7]}
        head = {"min": [-0.15, -0.15, 1.4], "max": [0.15, 0.15, 1.9]}
        plan = humanoid_bones(body, head)
        self.assertEqual(plan["axis"], {"up": "+Z", "forward": "-Y"})
        self.assertEqual(plan["rest_pose"], "estimated_A_pose")
        self.assertEqual(plan["height"], 1.9)
        bones = {bone["name"]: bone for bone in plan["bones"]}
        self.assertEqual(len(bones), 20)
        self.assertEqual(bones["root"]["parent"], None)
        self.assertEqual(bones["head"]["parent"], "neck")
        self.assertEqual(bones["foot.L"]["parent"], "shin.L")
        for bone in bones.values():
            self.assertNotEqual(bone["head"], bone["tail"])
            self.assertTrue(all(math.isfinite(v) for v in bone["head"] + bone["tail"]))
            if bone["parent"]:
                self.assertIn(bone["parent"], bones)
        self.assertGreater(bones["upper_arm.L"]["tail"][0], 0)
        self.assertLess(bones["upper_arm.R"]["tail"][0], 0)
        self.assertAlmostEqual(
            bones["upper_arm.L"]["tail"][0], -bones["upper_arm.R"]["tail"][0]
        )
        self.assertLess(bones["foot.L"]["tail"][1], 0)

    def test_bad_bounds_rejected_before_blender(self):
        with self.assertRaisesRegex(ValueError, "finite and non-degenerate"):
            humanoid_bones({"min": [0, 0, 0], "max": [0, 0, 0]})
        with self.assertRaisesRegex(ValueError, "Implausible"):
            humanoid_bones({"min": [0, 0, 0], "max": [1, 1, 1000]})


class RigPrototypeCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "outputs"
        self.prefix = "mara_rig_smoke"
        self.args = [
            "--card", str(CARD), "--prefix", self.prefix,
            "--output-dir", str(self.root),
        ]

    def opts(self, *extra):
        return options(self.args + list(extra))

    def make_assembly(self):
        paths = plan_paths(self.opts())
        paths["assembly_folder"].mkdir(parents=True)
        paths["assembly_blend"].write_bytes(b"untouched-scene")
        paths["assembly_manifest"].write_text(json.dumps({
            "character_id": load_card(CARD)["id"],
            "run_prefix": self.prefix,
            "preview_layout": "overlay",
            "parts": [{"id": "body"}, {"id": "head"}],
        }), encoding="utf-8")
        return paths

    def fake_blender(self):
        fake = Path(self.tmp.name) / "blender"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "args = sys.argv\n"
            "script = pathlib.Path(args[args.index('--python')+1]).name\n"
            "marker = pathlib.Path(__file__).with_suffix('.log')\n"
            "with marker.open('a') as log: log.write(script + '\\n')\n"
            "report = pathlib.Path(args[args.index('--report')+1])\n"
            "if script == 'blender_prototype.py':\n"
            "  out = pathlib.Path(args[args.index('--output')+1])\n"
            "  out.write_bytes(b'FAKE-RIG-SCENE')\n"
            "  report.write_text(json.dumps({'bones':[{'name':'root'}],"
            "'component_objects':['body_mesh','head_mesh'],"
            "'skinned':False,'animated':False}))\n"
            "elif script == 'blender_verify.py':\n"
            "  scene = pathlib.Path(args[args.index('--blend')+1])\n"
            "  assert scene.read_bytes() == b'FAKE-RIG-SCENE'\n"
            "  assert json.loads(report.read_text())['skinned'] is False\n"
            "else: sys.exit(6)\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return fake

    def test_dry_run_never_creates_output(self):
        p = build(self.opts("--dry-run"))
        self.assertFalse(self.root.exists())
        self.assertEqual(p["rig_blend"].name, "rig_prototype.blend")

    def test_missing_assembly_fails_before_writing_anything(self):
        with self.assertRaisesRegex(RuntimeError, "Missing existing assembly manifest"):
            build(self.opts("--blender", "/usr/bin/false"))
        self.assertFalse(self.root.exists())

    def test_offline_fake_blender_and_existing_output_protection(self):
        paths = self.make_assembly()
        source = paths["assembly_blend"].read_bytes()
        blend = self.fake_blender()
        build(self.opts("--blender", str(blend)))
        self.assertEqual(paths["rig_blend"].read_bytes(), b"FAKE-RIG-SCENE")
        self.assertEqual(
            blend.with_suffix(".log").read_text().splitlines(),
            ["blender_prototype.py", "blender_verify.py"],
        )
        self.assertEqual(paths["assembly_blend"].read_bytes(), source)
        self.assertFalse(list(paths["target_folder"].glob("*.blend1")))
        report = json.loads(paths["report"].read_text())
        self.assertFalse(report["skinned"])
        self.assertFalse(report["animated"])
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            build(self.opts("--blender", str(blend)))
        build(self.opts("--blender", str(blend), "--force"))
        self.assertEqual(paths["assembly_blend"].read_bytes(), source)

    def test_explicit_manual_scene_rigged_without_manifest_or_overwriting_old_rig(self):
        # The exact hand-edited scene must take precedence over generated previews.
        manual = self.root / "mara_complete_v1_landmark_v2" / "mara_manual_fit_v1.blend"
        manual.parent.mkdir(parents=True)
        manual.write_bytes(b"MANUAL-FITTED-MARA-SOURCE")
        old_rig = self.root / (self.prefix + "_rig_prototype") / "rig_prototype.blend"
        old_rig.parent.mkdir()
        old_rig.write_bytes(b"EARLIER-RIG-UNCHANGED")
        new_name = self.prefix + "_manual_fit_rig"
        opts = self.opts(
            "--source-blend", str(manual),
            "--rig-name", new_name,
            "--blender", str(self.fake_blender()),
        )
        paths = plan_paths(opts)
        self.assertEqual(paths["assembly_blend"], manual.resolve())
        self.assertIsNone(paths["assembly_manifest"])
        self.assertEqual(paths["target_folder"].name, new_name)
        build(opts)
        self.assertEqual(paths["rig_blend"].read_bytes(), b"FAKE-RIG-SCENE")
        self.assertEqual(manual.read_bytes(), b"MANUAL-FITTED-MARA-SOURCE")
        self.assertEqual(old_rig.read_bytes(), b"EARLIER-RIG-UNCHANGED")
        # Source must be the Blender scene passed before --python.
        self.assertTrue(paths["report"].is_file())

    def test_explicit_rig_source_must_be_blend_and_destination_must_differ(self):
        manual = self.root / "manual" / "scene.blend"
        with self.assertRaisesRegex(RuntimeError, "source scene directory"):
            plan_paths(self.opts("--source-blend", str(manual),
                                 "--rig-name", "manual"))
        with self.assertRaisesRegex(RuntimeError, "must be a .blend"):
            plan_paths(self.opts("--source-blend", str(manual.with_suffix(".glb"))))
        with self.assertRaises(SystemExit):
            self.opts("--source-blend", str(manual), "--assembly", "other_assembly")

    def test_explicit_source_shell_dry_run_avoids_reconstruction(self):
        manual = self.root / "mara_manual_fit_v1.blend"
        name = "manually_fitted_mara_rig"
        cmd = ["bash", str(ROOT / "build_character.sh"),
               "--rig-prototype", "--prefix", self.prefix,
               "--output-dir", str(self.root),
               "--source-blend", str(manual),
               "--rig-name", name, "--dry-run"]
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(str(manual), run.stdout)
        self.assertIn(name, run.stdout)
        self.assertFalse(self.root.exists())

    def test_wrong_character_is_rejected(self):
        paths = self.make_assembly()
        manifest = json.loads(paths["assembly_manifest"].read_text())
        manifest["character_id"] = "another_person"
        paths["assembly_manifest"].write_text(json.dumps(manifest))
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            build(self.opts("--blender", str(self.fake_blender())))
        self.assertFalse(paths["target_folder"].exists())

    def test_shell_mode_is_real_and_rejects_incompatible_flags(self):
        cmd = ["bash", str(ROOT / "build_character.sh"),
               "--rig-prototype", "--prefix", self.prefix,
               "--output-dir", str(self.root)]
        result = subprocess.run(cmd + ["--dry-run"], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("[RIG PROTOTYPE]", result.stdout)
        self.assertFalse(self.root.exists())

        bad = subprocess.run(cmd + ["--assemble-workable", "--dry-run"], cwd=ROOT,
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("cannot be combined", bad.stderr)

        help_text = subprocess.run(["bash", str(ROOT / "build_character.sh"), "--help"],
                                   cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(help_text.returncode, 0)
        self.assertIn("--rig-prototype", help_text.stdout)


if __name__ == "__main__":
    unittest.main()
