"""Conservative humanoid A-pose landmarks based on assembled mesh bounds.

This is a skeleton-placement *starting point*, not measured joints, retopology,
skin weights, or a guarantee that the mesh has anatomical topology. World Z up,
forward -Y (the existing Mara card coordinate system). No Blender dependency.
"""
from __future__ import annotations

import math


def _check_bounds(bounds, label):
    if not isinstance(bounds, dict):
        raise ValueError(f"{label} bounds are missing")
    try:
        lo = [float(value) for value in bounds["min"]]
        hi = [float(value) for value in bounds["max"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} bounds are invalid") from exc
    if (len(lo) != 3 or len(hi) != 3 or
            any(not math.isfinite(value) for value in lo + hi) or
            any(hi[i] <= lo[i] for i in range(3))):
        raise ValueError(f"{label} bounds must be finite and non-degenerate")
    return lo, hi


def humanoid_bones(body_bounds, head_bounds=None):
    """Return named parented edit-bone segments in the *world* A-pose.

    The body defines the center/ground. The separate head can extend the
    top-of-skull estimate, without using unrelated equipment/garment bounds.
    """
    body_lo, body_hi = _check_bounds(body_bounds, "body")
    top = body_hi[2]
    if head_bounds is not None:
        _, head_hi = _check_bounds(head_bounds, "head")
        top = max(top, head_hi[2])
    base = body_lo[2]
    height = top - base
    if not 0.2 <= height <= 100.0:
        raise ValueError(f"Implausible assembled humanoid height {height:.3f}")

    cx = (body_lo[0] + body_hi[0]) / 2
    cy = (body_lo[1] + body_hi[1]) / 2

    def pt(x, y, z):
        return (round(cx + x * height, 6),
                round(cy + y * height, 6),
                round(base + z * height, 6))

    bones = []

    def bone(name, parent, start, end):
        if start == end:
            raise ValueError(f"Zero-length bone: {name}")
        bones.append({
            "name": name, "parent": parent,
            "head": pt(*start), "tail": pt(*end),
        })

    bone("root", None, (0, 0, .02), (0, 0, .50))
    bone("pelvis", "root", (0, 0, .50), (0, 0, .56))
    bone("spine", "pelvis", (0, 0, .56), (0, 0, .68))
    bone("chest", "spine", (0, 0, .68), (0, 0, .81))
    bone("neck", "chest", (0, 0, .81), (0, 0, .87))
    bone("head", "neck", (0, 0, .87), (0, 0, .97))

    # A-pose arms point diagonally down and out. Side labels are Blender's
    # .L/.R names, using +X for left and -X for right in front view.
    for side, direction in (("L", 1), ("R", -1)):
        def arm(x, y, z):
            return (direction * x, y, z)

        bone(f"clavicle.{side}", "chest",
             arm(.015, 0, .795), arm(.115, 0, .81))
        bone(f"upper_arm.{side}", f"clavicle.{side}",
             arm(.115, 0, .81), arm(.225, 0, .655))
        bone(f"forearm.{side}", f"upper_arm.{side}",
             arm(.225, 0, .655), arm(.305, 0, .525))
        bone(f"hand.{side}", f"forearm.{side}",
             arm(.305, 0, .525), arm(.345, 0, .485))

        bone(f"thigh.{side}", "pelvis",
             arm(.078, 0, .50), arm(.086, 0, .29))
        bone(f"shin.{side}", f"thigh.{side}",
             arm(.086, 0, .29), arm(.087, 0, .067))
        bone(f"foot.{side}", f"shin.{side}",
             arm(.087, 0, .067), arm(.087, -.105, .035))

    names = {part["name"] for part in bones}
    if len(names) != len(bones) or any(
        item["parent"] is not None and item["parent"] not in names
        for item in bones
    ):
        raise ValueError("Broken armature hierarchy")

    return {
        "height": round(height, 6),
        "axis": {"up": "+Z", "forward": "-Y"},
        "rest_pose": "estimated_A_pose",
        "bones": bones,
        "warnings": [
            "Bone positions use height proportions, not anatomy landmarks.",
            "Nothing is weight-painted, skinned, animated, joined, or exported as a rigged GLB.",
            "Inspect shoulder, elbow, wrist, hip, knee, ankle, neck and head positions in Blender.",
        ],
    }
