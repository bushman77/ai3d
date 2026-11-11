"""Fail-closed geometry identification for Mara's remaining holster fragments.

These are candidates for an isolated *preview*, not deletion approvals.
Measured bounds and component sizes come from the user's experimental
topology report. Neither the original mesh nor its source assets are changed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from operator import index


@dataclass(frozen=True)
class IslandSignature:
    name: str
    vertices: int
    faces: int
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]


# I0050, I0060 and I0082 in the saved experimental topology report.
# IDs may be reassigned if vertex order changes; dimensions are independent.
MARA_REVIEW_SIGNATURES = (
    IslandSignature("lower_holster_rim", 62, 85,
                    (-0.263574, -0.121110, -0.287881),
                    (-0.183161, 0.048615, -0.266872)),
    IslandSignature("outer_holster_strip", 41, 51,
                    (-0.292287, -0.015643, -0.256425),
                    (-0.267891, 0.010245, -0.092461)),
    IslandSignature("lower_holster_tab", 12, 11,
                    (-0.237011, -0.089207, -0.326069),
                    (-0.204047, -0.047672, -0.287824)),
)


@dataclass
class RemnantSelection:
    names: tuple[str, ...]
    face_indices: tuple[int, ...]
    vertex_indices: tuple[int, ...]
    components: tuple[dict, ...]


def identify_remnant_islands(points, polygons, *,
                             signatures=MARA_REVIEW_SIGNATURES,
                             expected_mesh_counts=(20633, 33129),
                             bounds_tolerance=0.0002):
    """Return indices of exactly matching islands, without modifying geometry.

    Exact vertex/face counts AND world-space bounding boxes must match
    independently for every expected island. Missing or ambiguous matches
    abort the entire operation. Never remove by proximity alone.
    """
    if expected_mesh_counts is not None and (len(points), len(polygons)) != tuple(expected_mesh_counts):
        raise ValueError("Unexpected Mara body vertex/face totals; refusing remnant selection")
    if not signatures:
        raise ValueError("No explicit signatures were provided")
    if not math.isfinite(bounds_tolerance) or not (0 < bounds_tolerance <= 0.001):
        raise ValueError("Invalid bounds tolerance")
    n = len(points)
    for p in points:
        if len(p) != 3 or not all(math.isfinite(v) for v in p):
            raise ValueError("Body has invalid coordinates")

    parent = list(range(n))
    sizes = [1] * n

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if sizes[ra] < sizes[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        sizes[ra] += sizes[rb]

    for fid, poly in enumerate(polygons):
        try:
            indices = tuple(index(v) for v in poly)
        except TypeError as error:
            raise ValueError(f"Invalid polygon {fid}") from error
        if len(indices) < 3 or any(v < 0 or v >= n for v in indices):
            raise ValueError(f"Invalid polygon {fid}")
        for v in indices[1:]:
            union(indices[0], v)

    vertices_by_root = defaultdict(list)
    for i in range(n):
        vertices_by_root[find(i)].append(i)
    faces_by_root = defaultdict(list)
    for fid, poly in enumerate(polygons):
        faces_by_root[find(index(poly[0]))].append(fid)

    candidates = []
    for root, vids in vertices_by_root.items():
        fids = faces_by_root[root]
        if not fids:
            continue
        lo = tuple(min(points[i][j] for i in vids) for j in range(3))
        hi = tuple(max(points[i][j] for i in vids) for j in range(3))
        candidates.append((root, vids, fids, lo, hi))

    selected = []
    used = set()
    for signature in signatures:
        matches = [candidate for candidate in candidates
                   if (len(candidate[1]) == signature.vertices
                       and len(candidate[2]) == signature.faces
                       and all(abs(candidate[3][j] - signature.minimum[j]) <= bounds_tolerance
                               and abs(candidate[4][j] - signature.maximum[j]) <= bounds_tolerance
                               for j in range(3)))]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one island matching {signature.name}; found {len(matches)}")
        root, vids, fids, lo, hi = matches[0]
        if root in used:
            raise ValueError(f"Duplicate matching island {signature.name}")
        used.add(root)
        selected.append({
            "name": signature.name,
            "vertex_count": len(vids),
            "face_count": len(fids),
            "bounds": {"min": list(lo), "max": list(hi)},
            "vertex_indices": tuple(sorted(vids)),
            "face_indices": tuple(sorted(fids)),
        })

    return RemnantSelection(
        names=tuple(d["name"] for d in selected),
        face_indices=tuple(sorted(i for d in selected for i in d["face_indices"])),
        vertex_indices=tuple(sorted(i for d in selected for i in d["vertex_indices"])),
        components=tuple(selected),
    )
