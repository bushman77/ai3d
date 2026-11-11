"""Fail-closed signature matching for Mara's visual-test remnant islands."""
import unittest
from ai3d.diagnostics.holster_review import IslandSignature, identify_remnant_islands


class RemnantReviewTest(unittest.TestCase):
    def setUp(self):
        self.points = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.),
                       (5., 0., 0.), (6., 0., 0.), (5., 1., 0.),
                       (10., 0., 0.), (11., 0., 0.), (10., 1., 0.)]
        self.polygons = [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
        self.signatures = (
            IslandSignature("first", 3, 1, (0., 0., 0.), (1., 1., 0.)),
            IslandSignature("second", 3, 1, (5., 0., 0.), (6., 1., 0.)),
        )

    def identify(self, **kwargs):
        return identify_remnant_islands(
            self.points, self.polygons, signatures=self.signatures,
            expected_mesh_counts=None, **kwargs
        )

    def test_exact_components_and_no_mutation(self):
        before_points, before_faces = list(self.points), list(self.polygons)
        selection = self.identify()
        self.assertEqual(selection.names, ("first", "second"))
        self.assertEqual(selection.face_indices, (0, 1))
        self.assertEqual(selection.vertex_indices, (0, 1, 2, 3, 4, 5))
        self.assertEqual(before_points, self.points)
        self.assertEqual(before_faces, self.polygons)

    def test_rejects_unexpected_source(self):
        with self.assertRaisesRegex(ValueError, "Unexpected Mara body"):
            identify_remnant_islands(self.points, self.polygons,
                                     signatures=self.signatures)

    def test_changed_geometry_fails_instead_of_guessing(self):
        self.points[3] = (4.9, 0., 0.)
        with self.assertRaisesRegex(ValueError, "second.*found 0"):
            self.identify()

    def test_missing_and_repeated_signatures_fail(self):
        absent = IslandSignature("absent", 3, 1, (2., 0., 0.), (3., 1., 0.))
        with self.assertRaisesRegex(ValueError, "absent"):
            identify_remnant_islands(
                self.points, self.polygons, signatures=(absent,),
                expected_mesh_counts=None,
            )
        with self.assertRaisesRegex(ValueError, "Duplicate matching island"):
            identify_remnant_islands(
                self.points, self.polygons,
                signatures=(self.signatures[0], self.signatures[0]),
                expected_mesh_counts=None,
            )

    def test_bad_tolerance_and_polygon_rejected(self):
        with self.assertRaises(ValueError):
            self.identify(bounds_tolerance=0.05)
        self.polygons[1] = (3, 4, 100)
        with self.assertRaisesRegex(ValueError, "Invalid polygon"):
            self.identify()


if __name__ == "__main__":
    unittest.main()
