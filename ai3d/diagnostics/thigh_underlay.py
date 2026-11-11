"""Mara Venn's non-destructive underlay prototype.

These stations were fitted manually to measurements taken from the user's
experimental thigh-hole Blender scene. This is NOT general character fitting,
topology repair, UV reconstruction, or a watertight merge with the body.
The underlay is its own CLOSED mesh, intended to sit behind existing clothing.
"""

from __future__ import annotations

import math

# Each station: world Z, world center X/Y, cross-section radii X/Y.
# The top/bottom are tapered inward to minimize visible hard cut-offs.
# These proportions are specific to the *current* Mara model, metres-ish
# Blender world units, with the experimental hole on the negative-X leg.
MARA_THIGH_STATIONS = (
    (-0.405, -0.158, -0.006, 0.070, 0.070),
    (-0.370, -0.157, -0.006, 0.086, 0.085),
    (-0.300, -0.156, -0.006, 0.096, 0.092),
    (-0.220, -0.152, -0.006, 0.105, 0.108),
    (-0.120, -0.151, -0.006, 0.109, 0.113),
    (-0.020, -0.149, -0.006, 0.102, 0.109),
    ( 0.060, -0.148, -0.006, 0.098, 0.101),
    ( 0.105, -0.148, -0.006, 0.077, 0.079),
)


def _interp(stations, z, index):
    if z <= stations[0][0]:
        return stations[0][index]
    if z >= stations[-1][0]:
        return stations[-1][index]
    for lower, upper in zip(stations[:-1], stations[1:]):
        if lower[0] <= z <= upper[0]:
            t = (z-lower[0])/(upper[0]-lower[0])
            return lower[index]*(1.0-t)+upper[index]*t
    raise AssertionError("Unreachable station interval")


def build_mara_underlay(*, rings=48, radial_segments=64, inset=0.0):
    """Return world-space (vertices, triangular faces) for a closed thigh shell.

    An inset > 0 shrinks both radii and can reduce surface intersections.
    This creates a non-welded diagnostic layer, NOT a repaired suit surface.
    """
    if rings < 3 or radial_segments < 8:
        raise ValueError("Require at least 3 rings and 8 radial segments")
    if not 0.0 <= inset < 0.03 or not math.isfinite(inset):
        raise ValueError("Inset must be finite and in the range [0, 0.03)")
    stations = MARA_THIGH_STATIONS
    vertices = []
    for k in range(rings):
        z = stations[0][0] + (stations[-1][0]-stations[0][0])*k/(rings-1)
        cx = _interp(stations, z, 1)
        cy = _interp(stations, z, 2)
        rx = _interp(stations, z, 3)-inset
        ry = _interp(stations, z, 4)-inset
        if rx <= 0 or ry <= 0:
            raise ValueError("Inset collapsed an underlay cross-section")
        for j in range(radial_segments):
            theta = 2*math.pi*j/radial_segments
            vertices.append((cx+rx*math.cos(theta),
                             cy+ry*math.sin(theta), z))

    faces = []
    for k in range(rings-1):
        for j in range(radial_segments):
            a = k*radial_segments + j
            b = k*radial_segments + (j+1) % radial_segments
            c = (k+1)*radial_segments + j
            d = (k+1)*radial_segments + (j+1) % radial_segments
            faces.append((a,b,c))
            faces.append((b,d,c))

    top = (rings-1)*radial_segments
    for j in range(1, radial_segments-1):
        faces.append((0, j+1, j))  # bottom cap
        faces.append((top, top+j, top+j+1))  # top cap
    return vertices, faces
