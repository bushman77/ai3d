"""Geometry-only tests for the intentionally Mara-specific thigh underlay."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai3d.diagnostics.thigh_underlay import build_mara_underlay, MARA_THIGH_STATIONS


class MaraThighPrototypeTest(unittest.TestCase):
    def test_closed_triangular_shell_dimensions(self):
        rings, segments = 15, 16
        vertices, faces = build_mara_underlay(rings=rings, radial_segments=segments)
        self.assertEqual(len(vertices), rings * segments)
        self.assertEqual(len(faces), 2*(rings-1)*segments + 2*(segments-2))
        self.assertAlmostEqual(min(p[2] for p in vertices), MARA_THIGH_STATIONS[0][0])
        self.assertAlmostEqual(max(p[2] for p in vertices), MARA_THIGH_STATIONS[-1][0])
        for xyz in vertices:
            self.assertTrue(all(math.isfinite(c) for c in xyz))
        incident = {}
        for face in faces:
            self.assertEqual(len(set(face)), 3)
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                key = tuple(sorted((a, b)))
                incident[key] = incident.get(key, 0)+1
        self.assertTrue(incident)
        self.assertTrue(all(degree == 2 for degree in incident.values()),
                        "Every edge must be shared by exactly two triangles")

    def test_inset_shrinks_cross_sections(self):
        a, _ = build_mara_underlay(rings=8, radial_segments=16)
        b, _ = build_mara_underlay(rings=8, radial_segments=16, inset=0.006)
        for va, vb in zip(a, b):
            self.assertAlmostEqual(va[2], vb[2])
        self.assertLess(max(v[0] for v in b)-min(v[0] for v in b),
                        max(v[0] for v in a)-min(v[0] for v in a))

    def test_invalid_config_rejected(self):
        for kwargs in ({"rings": 2}, {"radial_segments": 7},
                       {"inset": -0.001}, {"inset": 0.035},
                       {"inset": float("nan")}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    build_mara_underlay(**kwargs)


if __name__ == "__main__":
    unittest.main()
