"""Merging Mixamo clips onto the rig, run in real Blender.

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

BLENDER = os.environ.get("AI3D_BLENDER") or shutil.which("blender")
FIXTURE = Path(__file__).with_name("blender_gestures_fixture.py")


@unittest.skipUnless(BLENDER, "Blender not available")
class GestureMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        out = cls.dir / "gestures.json"
        result = subprocess.run(
            [BLENDER, "--background", "--factory-startup", "--python", str(FIXTURE),
             "--", "--out", str(out)],
            capture_output=True, text=True, timeout=900)
        if not out.is_file():
            raise AssertionError(result.stdout[-3000:] + result.stderr[-3000:])
        cls.report = json.loads(out.read_text())

    def test_the_clip_is_named_after_its_file(self):
        self.assertEqual(self.report["made"], ["brush_shoulder"])

    def test_bones_the_skeleton_lacks_are_dropped(self):
        bones = self.report["bones"]
        self.assertTrue(bones, "the merged clip drives no bones")
        self.assertNotIn("mixamorig:LeftHandIndex1", bones,
                         "this rig has no fingers; Mixamo's finger curves must be dropped")
        self.assertIn("mixamorig:LeftArm", bones)

    def test_only_rotation_is_taken(self):
        # Translation would move an attendant off the spot the server gave it.
        self.assertTrue(self.report["rotation_only"])

    def test_motion_survives_a_different_rest_pose(self):
        # Source rests in a T, target in an A. A raw copy would be wrong by the
        # angle between them; a retarget reaches the same rotation.
        self.assertAlmostEqual(self.report["reached_degrees"],
                               self.report["turn_degrees"], delta=1.0)
        self.assertLess(self.report["axis_error_degrees"], 1.0,
                        "retargeted rotation points the wrong way")

    def test_the_clip_starts_from_rest(self):
        self.assertLess(self.report["rest_degrees"], 1.0)

    def test_the_import_leaves_no_stray_actions(self):
        # Blender's FBX importer sets a fake user on imported actions, so a
        # refcount check never removes them and they reach the exported GLB
        # as clips driving bones this skeleton does not have.
        self.assertEqual(self.report["actions_left"], ["brush_shoulder"],
                         "the imported clip's own action was left behind")

    def test_keys_never_flip_hemisphere(self):
        # q and -q are the same rotation, but a sign flip between keys makes
        # Blender interpolate the long way round, which spikes the mesh.
        self.assertGreater(self.report["baked_keys"], 1)
        self.assertGreaterEqual(self.report["worst_dot"], 0.0,
                                "a baked key flipped to the opposite hemisphere")

    def test_no_single_frame_spins_the_bone(self):
        # The source sweeps smoothly through a full turn, so no one frame
        # should carry a large jump however far the total rotation goes.
        self.assertLess(self.report["worst_step_degrees"], 90.0)


if __name__ == "__main__":
    unittest.main()
