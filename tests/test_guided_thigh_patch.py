"""Blender-free tests for Mara's mesh-guided thigh prototype."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai3d.diagnostics.guided_thigh_patch import build_mesh_guided_thigh_patch


def fixture(*, include_rear=True, add_holster=False):
    points, faces = [], []
    for rear in (False, True):
        if rear and not include_rear:
            continue
        offset = len(points)
        nz, nx = 48, 25
        for iz in range(nz):
            z = -0.96 + 1.12*iz/(nz-1)
            for j in range(nx):
                t = j/(nx-1)
                x = -0.105 - 0.135*t + 0.008*math.sin(z*7)
                y = (0.060+0.045*t) if rear else (-0.060-0.045*t)
                points.append((x, y, z))
        for iz in range(nz-1):
            for j in range(nx-1):
                a = offset+iz*nx+j
                faces.extend(((a, a+1, a+nx), (a+1, a+nx+1, a+nx)))
    if add_holster:
        # An accessory island is geometrically nearby but short in Z.
        offset = len(points)
        for i in range(20):
            for j in range(20):
                points.append((-.34+0.001*j, -.03+0.001*i, -.25+.003*i))
        for i in range(19):
            for j in range(19):
                a = offset+i*20+j
                faces.extend(((a, a+1, a+20), (a+1, a+21, a+20)))
    return points, faces


class GuidedThighTest(unittest.TestCase):
    def test_uses_long_leg_surfaces_not_short_holster(self):
        points, faces = fixture(add_holster=True)
        before = copy.deepcopy(points)
        verts, tris, metrics = build_mesh_guided_thigh_patch(points, faces)
        self.assertEqual(points, before)
        self.assertEqual(metrics["source_islands"], 2)
        self.assertEqual(metrics["front_supported_rings"], 34)
        self.assertEqual(metrics["rear_supported_rings"], 34)
        self.assertEqual(len(verts), 34*18)
        self.assertEqual(len(tris), 2*33*17)
        self.assertGreater(min(p[0] for p in verts), -.29)
        self.assertEqual(metrics["method"], "mesh_guided_open_side_panel")
        for ring, anchor in enumerate(metrics["anchors"]):
            outer = min(anchor["front"][0], anchor["back"][0])
            self.assertGreaterEqual(
                min(verts[ring*18+j][0] for j in range(18)), outer-.004001
            )
            self.assertAlmostEqual(verts[ring*18][0], anchor["front"][0], places=5)
            self.assertAlmostEqual(verts[ring*18+17][0], anchor["back"][0], places=5)
        self.assertLess(verts[0][1], 0)
        self.assertGreater(verts[17][1], 0)

    def test_missing_rear_surface_fails_without_guessing(self):
        points, faces = fixture(include_rear=False)
        with self.assertRaisesRegex(ValueError, "Expected 2-5 continuous"):
            build_mesh_guided_thigh_patch(points, faces)

    def test_inset_moves_panel_inward(self):
        points, faces = fixture()
        original, _, _ = build_mesh_guided_thigh_patch(points, faces)
        inset, _, _ = build_mesh_guided_thigh_patch(points, faces, inset=.005)
        for a, b in zip(original, inset):
            self.assertAlmostEqual(b[0]-a[0], .005)
            self.assertEqual(a[1:], b[1:])

    def test_invalid_parameters_rejected(self):
        points, faces = fixture()
        for params in ({"rings": 4}, {"width_segments": 2},
                       {"inset": -.01}, {"inset": float("nan")},
                       {"z_min": -.6}, {"z_max": .05}):
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    build_mesh_guided_thigh_patch(points, faces, **params)


if __name__ == "__main__":
    unittest.main()
