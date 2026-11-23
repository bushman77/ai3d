"""Mara-specific mesh-guided outer thigh panel (Blender-independent).

Select substantial connected leg-surface islands, sample front and rear
surface contours, and interpolate a narrow *open* panel between them. No
holster removal, welding, UV mapping, materials, or final garment repair.
"""

from collections import defaultdict
import math

GUIDED_Z_MIN = -0.385
GUIDED_Z_MAX = -0.065


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _island_vertices(points, faces):
    parent = list(range(len(points)))
    rank = [0] * len(points)

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    for face in faces:
        if len(face) < 3:
            raise ValueError("Mesh contains a polygon with fewer than three vertices")
        first = face[0]
        for other in face[1:]:
            union(first, other)
    groups = defaultdict(list)
    for i in range(len(points)):
        groups[find(i)].append(i)
    return list(groups.values())


def _outer_anchor(samples):
    """Median of the outermost 16% along X, rejecting short-lived outliers."""
    if len(samples) < 5:
        return None
    ordered = sorted(samples, key=lambda p: p[0])
    take = max(3, math.ceil(len(ordered) * 0.16))
    outer = ordered[:take]
    return (_median([p[0] for p in outer]), _median([p[1] for p in outer]))


def _fill_sparse(values, name):
    known = [i for i, value in enumerate(values) if value is not None]
    if len(known) < max(5, math.ceil(0.72 * len(values))):
        raise ValueError(f"Insufficient {name} support for mesh-guided fitting")
    if known[0] > 2 or len(values) - 1 - known[-1] > 2:
        raise ValueError(f"{name} surface is missing at a panel endpoint")
    filled = list(values)
    for i in range(len(values)):
        if filled[i] is not None:
            continue
        lo = next((k for k in range(i-1, -1, -1) if values[k] is not None), None)
        hi = next((k for k in range(i+1, len(values)) if values[k] is not None), None)
        if lo is None:
            filled[i] = values[hi]
        elif hi is None:
            filled[i] = values[lo]
        else:
            t = (i-lo)/(hi-lo)
            filled[i] = tuple(values[lo][j]*(1-t) + values[hi][j]*t for j in range(2))
    # Moderate axial smoothing, only along the surviving support samples.
    smoothed = []
    for i in range(len(values)):
        previous = filled[max(0, i-1)]
        current = filled[i]
        following = filled[min(len(values)-1, i+1)]
        smoothed.append(tuple(
            0.2*previous[j] + 0.6*current[j] + 0.2*following[j]
            for j in range(2)
        ))
    return smoothed, len(known)


def build_mesh_guided_thigh_patch(points, faces, *, rings=34, width_segments=18,
                                  inset=0.0, edge_embed=0.0, z_min=GUIDED_Z_MIN,
                                  z_max=GUIDED_Z_MAX):
    """Return (world vertices, triangle indices, fitting diagnostics).

    The result is an OPEN side panel with unwelded perimeter edges. Neither
    points nor faces are modified. Explicitly fail if both surviving leg
    contours cannot be measured reliably.
    """
    if rings < 8 or width_segments < 3 or z_min >= z_max:
        raise ValueError("Need at least 8 rings, 3 width segments and ascending Z")
    if not math.isfinite(inset) or not 0 <= inset < 0.03:
        raise ValueError("Inset must be finite and between 0 and 0.03")
    if not math.isfinite(edge_embed) or not 0 <= edge_embed <= 0.012:
        raise ValueError("Edge embed must be finite and between 0 and 0.012")
    if len(points) < 200 or not faces:
        raise ValueError("Missing mesh surface samples")
    if any(len(point) != 3 or not all(math.isfinite(v) for v in point)
           for point in points):
        raise ValueError("Mesh contains malformed/non-finite coordinates")
    if not (-0.50 <= z_min < -0.20 and -0.15 <= z_max <= 0.0):
        raise ValueError("Only the measured Mara thigh region is supported")

    groups = _island_vertices(points, faces)
    min_sample_size = max(100, math.ceil(len(points) * 0.015))
    candidates = []
    for group in groups:
        if len(group) < min_sample_size:
            continue
        xs = [points[i][0] for i in group]
        zs = [points[i][2] for i in group]
        if (min(zs) < -0.70 and max(zs) > -0.15 and
                min(xs) < -0.19 and max(xs) < 0.30):
            candidates.append(group)
    # Fail closed instead of silently sampling other anatomy/accessories.
    if not 2 <= len(candidates) <= 5:
        raise ValueError(
            f"Expected 2-5 continuous leg-surface islands; got {len(candidates)}"
        )

    sampled = [points[i] for group in candidates for i in group
               if points[i][0] < -0.085]
    heights = [z_min + (z_max-z_min)*k/(rings-1) for k in range(rings)]
    front, back = [], []
    for z in heights:
        band = [p for p in sampled if abs(p[2]-z) <= 0.022]
        front.append(_outer_anchor([p for p in band if p[1] <= -0.045]))
        back.append(_outer_anchor([p for p in band if p[1] >= 0.045]))
    front, n_front = _fill_sparse(front, "front thigh")
    back, n_back = _fill_sparse(back, "rear thigh")

    vertices, anchors = [], []
    for k, z in enumerate(heights):
        fx, fy = front[k]
        bx, by = back[k]
        if not (fy < -0.035 and by > 0.035 and by-fy > 0.095):
            raise ValueError(f"Invalid front/rear spacing at ring {k}")
        outer_x = min(fx, bx) - 0.004
        bulge = min(0.018, 0.08*(by-fy))
        anchors.append({
            "z": round(z, 6),
            "front": [round(fx, 6), round(fy, 6)],
            "back": [round(bx, 6), round(by, 6)],
        })
        for j in range(width_segments):
            t = j / (width_segments-1)
            x = (1-t)*fx + t*bx - bulge*math.sin(math.pi*t)
            # Smoothly bury the four perimeter edges under extant clothing.
            # This is cosmetic seam feathering, NOT topology welding.
            axial = max(0.0, 1.0 - min(k, rings-1-k) / max(1.0, rings*0.12))
            lateral = max(0.0, 1.0 - min(j, width_segments-1-j) /
                          max(1.0, width_segments*0.17))
            x = max(x, outer_x) + inset + edge_embed * max(axial, lateral)
            y = (1-t)*fy + t*by
            vertices.append((x, y, z))

    triangles = []
    for k in range(rings-1):
        for j in range(width_segments-1):
            a = k*width_segments+j
            b = a+1
            c = (k+1)*width_segments+j
            d = c+1
            triangles.extend(((a, c, b), (b, c, d)))  # facing outward (-X)

    diagnostics = {
        "method": "mesh_guided_open_side_panel",
        "source_islands": len(candidates),
        "source_surface_vertices": len(sampled),
        "front_supported_rings": n_front,
        "rear_supported_rings": n_back,
        "rings": rings,
        "width_segments": width_segments,
        "anchors": anchors,
        "inset": inset,
        "edge_embed": edge_embed,
        "notes": [
            "Diagnostic OPEN surface, not welded to body",
            "No accessory, UV, texture, or normals reconstruction",
            "Contour anchors approximate the edge; they are not exact seam vertices",
        ],
    }
    return vertices, triangles, diagnostics
