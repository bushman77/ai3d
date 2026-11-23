"""Runs the real Blender stages on a generated mannequin.

Skipped unless Blender is available: set AI3D_BLENDER=/path/to/blender or
have `blender` on PATH. CI uses a wrapper around the `bpy` pip package.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ai3d.blender.commands import blender_command
from ai3d.export.validation import readable_glb

BLENDER = os.environ.get("AI3D_BLENDER") or shutil.which("blender")
FIXTURE = Path(__file__).with_name("blender_fixture.py")


def gltf_json(path):
    import struct
    data = Path(path).read_bytes()
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


def blender(script_cmd):
    result = subprocess.run(script_cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise AssertionError(result.stdout[-3000:] + result.stderr[-3000:])
    return result.stdout


@unittest.skipUnless(BLENDER, "Blender not available (set AI3D_BLENDER)")
class BlenderStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        for name, extra in (("mannequin-y", ["--face", "-y"]), ("mannequin+y", ["--face", "+y"]),
                            ("wide_tpose", ["--hips", "wide", "--pose", "t"])):
            out = cls.dir / f"{name}.glb"
            blender([BLENDER, "--background", "--factory-startup", "--python-exit-code", "1",
                     "--python", str(FIXTURE), "--", str(out), *extra])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def stage(self, script, args):
        return blender(blender_command(BLENDER, script, [str(a) for a in args]))

    def stats(self, name):
        return json.loads((self.dir / name).read_text())

    def test_full_chain(self):
        src = self.dir / "mannequin-y.glb"
        pm, game, rigged = (self.dir / n for n in ("pm.glb", "game.glb", "rigged.glb"))
        self.stage("prepaint.py", ["--input", src, "--output", pm, "--target-faces", 2000,
                                   "--stats", self.dir / "pm.json"])
        self.assertLessEqual(self.stats("pm.json")["output_triangles"], 2000)

        self.stage("retopo_bake.py", ["--input", src, "--output", game, "--target-faces", 2500,
                                      "--texture-size", 256, "--samples", 1,
                                      "--stats", self.dir / "game.json"])
        g = self.stats("game.json")
        self.assertEqual(set(g["baked"]), {"basecolor", "normal", "roughness"})
        self.assertEqual(g["low_pieces"], 1)
        self.assertEqual(g["shape_pieces"], 1)
        self.assertGreater(g["head_uv_share"], 0.15)  # head boost on
        self.assertGreater(g["source_gutters_filled"]["fixture_albedo"], 0.1)
        if g["method"] == "quadriflow":
            self.assertGreater(g["low_quads_fraction"], 0.95)
        self.assertLess(g["surface_error_mean"], 0.01)
        info = readable_glb(game, need_texture=True)
        self.assertEqual(info["images"], 3)

        self.stage("rig.py", ["--input", game, "--output", rigged, "--stats", self.dir / "rig.json"])
        r = self.stats("rig.json")
        self.assertEqual(r["weight_method"], "heat")
        self.assertLess(r["unweighted_after_heat_fraction"], 0.02)
        self.assertEqual(r["unweighted_final"], 0)
        self.assertLessEqual(r["max_influences"], 4)
        self.assertEqual(r["deform_bones"], 22)
        self.assertEqual(r["deform_bones_without_vertices"], [])
        self.assertFalse(r["turned_to_face_minus_y"])
        self.assertEqual(r["arm_leak"], 0.0)
        self.assertTrue(rigged.with_suffix(".blend").is_file())
        self.assertEqual(r["actions"], ["idle", "ai3d_pose_test"])
        self.assertGreaterEqual(r["idle_arm_angle_deg"], 12.0)
        names = [anim["name"] for anim in gltf_json(rigged)["animations"]]
        self.assertIn("idle", names)

        self.stage("quality.py", ["--mesh", rigged, "--stats", self.dir / "q.json"])
        q = self.stats("q.json")
        self.assertEqual(q["mesh"]["pieces"], 1)
        self.assertEqual(q["mesh"]["boundary_edges"], 0)
        self.assertEqual(q["rig"]["bones"], 25)
        self.assertAlmostEqual(q["mesh"]["size_m"][2], 1.74, delta=0.05)

    def test_decimated_triangle_mesh_still_gets_heat_weights(self):
        # Regression: glTF splits vertices at UV seams; heat weighting failed on
        # 100% of vertices for decimated meshes until the rig stage welded them.
        src = self.dir / "mannequin-y.glb"
        game, rigged = self.dir / "dec_game.glb", self.dir / "dec_rigged.glb"
        self.stage("retopo_bake.py", ["--input", src, "--output", game, "--method", "decimate",
                                      "--target-faces", 4000, "--texture-size", 128, "--samples", 1])
        self.stage("rig.py", ["--input", game, "--output", rigged, "--no-test-animation",
                              "--stats", self.dir / "dec_rig.json"])
        r = self.stats("dec_rig.json")
        self.assertLess(r["unweighted_after_heat_fraction"], 0.02)
        self.assertEqual(r["unweighted_final"], 0)

    def test_wide_hips_do_not_pull_the_shoulders_down(self):
        # Regression (Mara): hips wider than the chest were averaged into the
        # shoulder joint, so the arm bones sat by the hips and moved them.
        src = self.dir / "wide_tpose.glb"
        game, rigged = self.dir / "wide_game.glb", self.dir / "wide_rigged.glb"
        self.stage("retopo_bake.py", ["--input", src, "--output", game, "--target-faces", 3000,
                                      "--texture-size", 128, "--samples", 1])
        self.stage("rig.py", ["--input", game, "--output", rigged, "--no-test-animation",
                              "--stats", self.dir / "wide_rig.json"])
        r = self.stats("wide_rig.json")
        # fixture shoulders at 1.40 m of 1.74 m = 0.80
        self.assertAlmostEqual(r["shoulder_height_fraction"], 0.80, delta=0.03)
        self.assertLess(r["arm_leak_before_trim"], 0.05)
        self.assertEqual(r["arm_leak"], 0.0)

    def test_backwards_character_is_turned(self):
        src = self.dir / "mannequin+y.glb"
        game, rigged = self.dir / "back_game.glb", self.dir / "back_rigged.glb"
        self.stage("retopo_bake.py", ["--input", src, "--output", game, "--target-faces", 1500,
                                      "--texture-size", 128, "--samples", 1])
        self.stage("rig.py", ["--input", game, "--output", rigged, "--no-test-animation",
                              "--stats", self.dir / "back_rig.json"])
        r = self.stats("back_rig.json")
        self.assertTrue(r["turned_to_face_minus_y"])
        self.assertIsNone(r["test_action"])
        self.assertEqual(r["actions"], ["idle"])


if __name__ == "__main__":
    unittest.main()
