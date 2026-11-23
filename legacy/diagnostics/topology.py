"""Pure-Python mesh topology inspection (no Blender dependency).

Coordinates are WORLD coordinates supplied by the Blender adapter.
A 'boundary' is an edge incident to exactly one face. Boundary components
are not automatically 'holes': seams, separate surfaces, and nonmanifold
geometry may also produce them.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import math
import struct


def _bounds(indices: list[int], points: list[tuple[float, float, float]]) -> dict:
    if not indices:
        raise ValueError("Cannot measure empty vertex set")
    lo = [min(points[i][j] for i in indices) for j in range(3)]
    hi = [max(points[i][j] for i in indices) for j in range(3)]
    return {
        "min": [round(v, 6) for v in lo],
        "max": [round(v, 6) for v in hi],
        "center": [round((a+b)/2, 6) for a, b in zip(lo, hi)],
        "size": [round(b-a, 6) for a, b in zip(lo, hi)],
    }


def _distance(a, b) -> float:
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))


def _boundary_groups(edge_indices, edges, points, owner):
    """Connected boundary-edge groups, independently of object islands."""
    adjacency = defaultdict(list)
    for index in edge_indices:
        u, v = edges[index]
        adjacency[u].append((v, index))
        adjacency[v].append((u, index))
    groups = []
    remaining = set(adjacency)
    while remaining:
        start = min(remaining)
        queue = [start]
        vertices = set()
        group_edges = set()
        while queue:
            v = queue.pop()
            if v in vertices:
                continue
            vertices.add(v)
            remaining.discard(v)
            for neighbor, edge_index in adjacency[v]:
                group_edges.add(edge_index)
                if neighbor not in vertices:
                    queue.append(neighbor)
        ordered_vertices = sorted(vertices)
        degrees = {v: len(adjacency[v]) for v in vertices}
        ends = [v for v, degree in degrees.items() if degree == 1]
        if len(group_edges) == len(vertices) and all(d == 2 for d in degrees.values()):
            kind = "closed_loop"
        elif len(ends) == 2 and len(group_edges) == len(vertices)-1 and all(
                d in (1, 2) for d in degrees.values()):
            kind = "open_chain"
        else:
            kind = "branched_or_complex"
        sequence = []
        if kind in ("closed_loop", "open_chain"):
            first = min(ends) if kind == "open_chain" else min(vertices)
            previous = None
            at = first
            # Walk each simple loop/chain; never attempt to order a branched graph.
            while len(sequence) < len(vertices):
                sequence.append(at)
                neighbors = sorted(n for n, _ in adjacency[at] if n != previous)
                if not neighbors:
                    break
                nxt = neighbors[0]
                if nxt == first:
                    break
                previous, at = at, nxt
        centroid = [round(sum(points[v][j] for v in vertices) / len(vertices), 6)
                    for j in range(3)]
        groups.append({
            "kind": kind,
            "island_id": owner[start],
            "edge_count": len(group_edges),
            "vertex_count": len(vertices),
            "length": round(sum(_distance(points[edges[e][0]], points[edges[e][1]])
                                for e in group_edges), 6),
            "bounds": _bounds(ordered_vertices, points),
            "centroid": centroid,
            "vertex_indices": sequence if sequence else ordered_vertices,
            "vertex_ordered": bool(sequence),
            "edge_indices": sorted(group_edges),
        })
    groups.sort(key=lambda g: (-g["edge_count"], g["island_id"], g["vertex_indices"][0]))
    for i, group in enumerate(groups, 1):
        group["id"] = f"B{i:04d}"
    return groups


def analyze_mesh(
    points: list[tuple[float, float, float]],
    edges: list[tuple[int, int]],
    faces: list[tuple[int, ...]],
    *,
    side: str = "negative-x",
) -> dict:
    """Analyze disconnected islands and boundary graphs with no mutations.

    The ROI is a heuristic thigh search window, measured relative to the
    entire object: lower 30-68% of body height and chosen half of X extent.
    It ranks candidates; it does not classify accessories or repair openings.
    """
    if side not in ("negative-x", "positive-x", "both"):
        raise ValueError(f"Invalid ROI side: {side}")
    n = len(points)
    if not n or not faces:
        raise ValueError("Expected a nonempty mesh with faces")
    if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError("All points must have three finite coordinates")

    edge_lookup = {}
    parent = list(range(n))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for eid, (a, b) in enumerate(edges):
        if not (0 <= a < n and 0 <= b < n) or a == b:
            raise ValueError(f"Invalid edge at index {eid}")
        key = (min(a, b), max(a, b))
        if key in edge_lookup:
            raise ValueError(f"Duplicate edge endpoints at index {eid}")
        edge_lookup[key] = eid
        union(a, b)

    # Face-edge usage identifies true boundary, wire and high-valence edges.
    usage = [0] * len(edges)
    tri_count_by_root = defaultdict(int)
    face_count_by_root = defaultdict(int)
    for fid, face in enumerate(faces):
        if len(face) < 3 or any(v < 0 or v >= n for v in face):
            raise ValueError(f"Invalid polygon at index {fid}")
        root = find(face[0])
        if any(find(v) != root for v in face):
            raise ValueError(f"Disconnected vertices in face {fid}")
        face_count_by_root[root] += 1
        tri_count_by_root[root] += len(face)-2
        for i, a in enumerate(face):
            b = face[(i+1) % len(face)]
            eid = edge_lookup.get((min(a, b), max(a, b)))
            if eid is None:
                raise ValueError(f"Face {fid} refers to an absent mesh edge")
            usage[eid] += 1

    roots = defaultdict(list)
    for i in range(n):
        roots[find(i)].append(i)
    ordered_roots = sorted(roots, key=lambda r: (-len(roots[r]), r))
    island_id = {root: f"I{i:04d}" for i, root in enumerate(ordered_roots, 1)}
    owner = [island_id[find(i)] for i in range(n)]

    edge_count = defaultdict(int)
    boundary_count = defaultdict(int)
    for eid, (a, b) in enumerate(edges):
        group = owner[a]
        edge_count[group] += 1
        if usage[eid] == 1:
            boundary_count[group] += 1

    islands = []
    for root in ordered_roots:
        indices = roots[root]
        digest = hashlib.sha256()
        for v in indices:
            digest.update(struct.pack("<I3d", v, *points[v]))
        islands.append({
            "id": island_id[root],
            "vertex_count": len(indices),
            "edge_count": edge_count[island_id[root]],
            "face_count": face_count_by_root[root],
            "triangle_count": tri_count_by_root[root],
            "boundary_edge_count": boundary_count[island_id[root]],
            "bounds": _bounds(indices, points),
            "vertex_fingerprint": digest.hexdigest(),
            "first_vertex_index": indices[0],
        })

    boundary_indices = [i for i, count in enumerate(usage) if count == 1]
    boundaries = _boundary_groups(boundary_indices, edges, points, owner)

    whole = _bounds(list(range(n)), points)
    low_z = whole["min"][2] + whole["size"][2] * 0.30
    high_z = whole["min"][2] + whole["size"][2] * 0.68
    middle_x = whole["center"][0]
    def in_roi(v):
        x, _, z = points[v]
        correct_side = (side == "both" or
                        (side == "negative-x" and x <= middle_x) or
                        (side == "positive-x" and x >= middle_x))
        return correct_side and low_z <= z <= high_z

    candidates = []
    for group in boundaries:
        count = sum(in_roi(i) for i in group["vertex_indices"])
        if (count or (
                group["bounds"]["max"][2] >= low_z and
                group["bounds"]["min"][2] <= high_z and
                (side == "both" or
                 (side == "negative-x" and group["bounds"]["min"][0] <= middle_x) or
                 (side == "positive-x" and group["bounds"]["max"][0] >= middle_x))
            )):
            candidates.append({
                "boundary_id": group["id"],
                "island_id": group["island_id"],
                "kind": group["kind"],
                "vertices_in_roi": count,
                "boundary_vertices": group["vertex_count"],
                "boundary_edges": group["edge_count"],
                "length": group["length"],
                "bounds": group["bounds"],
            })
    candidates.sort(key=lambda c: (-c["vertices_in_roi"], -c["boundary_edges"], c["boundary_id"]))

    return {
        "schema_version": 1,
        "coordinate_space": "world",
        "overview": {
            "vertices": n,
            "edges": len(edges),
            "faces": len(faces),
            "triangles": sum(len(face)-2 for face in faces),
            "mesh_islands": len(islands),
            "boundary_edges": len(boundary_indices),
            "wire_edges": sum(count == 0 for count in usage),
            "nonmanifold_edges_over_two_faces": sum(count > 2 for count in usage),
            "boundary_groups": len(boundaries),
            "closed_boundary_loops": sum(b["kind"] == "closed_loop" for b in boundaries),
            "open_boundary_chains": sum(b["kind"] == "open_chain" for b in boundaries),
            "complex_boundary_groups": sum(b["kind"] == "branched_or_complex" for b in boundaries),
        },
        "object_bounds": whole,
        "roi": {
            "description": "Heuristic thigh region; NOT an accessory detector",
            "side": side,
            "x_split": round(middle_x, 6),
            "z_min": round(low_z, 6),
            "z_max": round(high_z, 6),
            "candidate_boundary_group_count": len(candidates),
        },
        "roi_candidates": candidates,
        "islands": islands,
        "boundary_groups": boundaries,
        "warnings": [
            "A boundary group is not proof of a hole; existing mesh seams can be open.",
            "Disconnected mesh islands may be parts of the same accessory or essential anatomy.",
            "Do not remove or fill geometry based only on this report.",
            "Vertex indices are valid only for this exact saved mesh topology.",
        ],
    }
