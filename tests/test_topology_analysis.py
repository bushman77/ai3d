"""Unit tests for topology inspection without Blender or AI backends."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai3d.diagnostics.topology import analyze_mesh


class TopologyAnalysisTest(unittest.TestCase):
    @staticmethod
    def quad(x):
        return (
            [(x, 0.0, 0.4), (x+1.0, 0.0, 0.4),
             (x+1.0, 0.0, 0.6), (x, 0.0, 0.6)],
            [(0, 1), (1, 2), (2, 3), (3, 0), (0, 2)],
            [(0, 1, 2), (0, 2, 3)],
        )

    def test_open_quad_has_one_closed_boundary_loop(self):
        p, e, f = self.quad(-2)
        result = analyze_mesh(p, e, f)
        self.assertEqual(result["overview"]["mesh_islands"], 1)
        self.assertEqual(result["overview"]["boundary_edges"], 4)
        self.assertEqual(result["overview"]["closed_boundary_loops"], 1)
        self.assertEqual(result["boundary_groups"][0]["kind"], "closed_loop")
        self.assertEqual(result["boundary_groups"][0]["vertex_count"], 4)

    def test_two_unconnected_surfaces_produce_two_islands_and_roi(self):
        p, e, f = self.quad(-2)
        q, g, h = self.quad(1)
        p += q
        e += [(a+4, b+4) for a, b in g]
        f += [tuple(a+4 for a in face) for face in h]
        result = analyze_mesh(p, e, f, side="negative-x")
        self.assertEqual(result["overview"]["mesh_islands"], 2)
        self.assertEqual(result["overview"]["closed_boundary_loops"], 2)
        self.assertEqual(len(result["roi_candidates"]), 1)
        self.assertEqual(result["roi_candidates"][0]["vertices_in_roi"], 0)
        pos = analyze_mesh(p, e, f, side="positive-x")
        self.assertEqual(len(pos["roi_candidates"]), 1)
        both = analyze_mesh(p, e, f, side="both")
        self.assertEqual(len(both["roi_candidates"]), 2)

    def test_closed_tetrahedron_has_no_boundaries(self):
        p = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        e = [(0, 1), (0, 2), (0, 3),
             (1, 2), (1, 3), (2, 3)]
        f = [(0, 1, 2), (0, 3, 1),
             (0, 2, 3), (1, 3, 2)]
        result = analyze_mesh(p, e, f)
        self.assertEqual(result["overview"]["boundary_edges"], 0)
        self.assertEqual(result["overview"]["boundary_groups"], 0)

    def test_wire_edge_is_not_mistaken_for_hole(self):
        p, e, f = self.quad(-2)
        p += [(-3, 0, 0), (-3, 0, 1)]
        e += [(4, 5)]
        result = analyze_mesh(p, e, f)
        self.assertEqual(result["overview"]["wire_edges"], 1)
        self.assertEqual(result["overview"]["boundary_edges"], 4)
        self.assertEqual(result["overview"]["mesh_islands"], 2)

    def test_missing_edge_fails(self):
        p, e, f = self.quad(-2)
        with self.assertRaisesRegex(ValueError, "absent mesh edge"):
            analyze_mesh(p, e[:-1], f)

    def test_branches_are_not_claimed_as_simple_loops(self):
        # Two triangles share one vertex, but no edge: one vertex-connectivity
        # island and a figure-eight boundary graph with degree 4 at vertex 0.
        p = [(0, 0, 0), (-1, 0, 0), (0, 1, 0), (1, 0, 0), (0, -1, 0)]
        e = [(0, 1), (1, 2), (2, 0), (0, 3), (3, 4), (4, 0)]
        f = [(0, 1, 2), (0, 3, 4)]
        result = analyze_mesh(p, e, f)
        self.assertEqual(result["overview"]["mesh_islands"], 1)
        self.assertEqual(result["overview"]["complex_boundary_groups"], 1)
        self.assertFalse(result["boundary_groups"][0]["vertex_ordered"])


if __name__ == "__main__":
    unittest.main()
