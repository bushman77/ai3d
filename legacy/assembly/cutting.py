"""Configurable, reversible assembly cut-plane specification.

No Blender imports: card/manifest validation and CLI editing work on any
supported Python version. Plane heights are *world-space Blender Z units*,
and cutting is disabled unless mode='apply' is explicitly selected.
"""

from __future__ import annotations

import math

CUT_MODES = ("off", "guide", "apply")
KEEP_SIDES = ("above", "below")


def default_cut(*, keep: str) -> dict:
    if keep not in KEEP_SIDES:
        raise ValueError(f"Unknown kept half-space: {keep}")
    return {
        "mode": "off",
        "plane_z": 0.0,
        "keep": keep,
        "show_guide": True,
    }


def validate_cut(value: object, label: str = "cut") -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors = []
    if value.get("mode") not in CUT_MODES:
        errors.append(f"{label}.mode must be off, guide, or apply")
    if value.get("keep") not in KEEP_SIDES:
        errors.append(f"{label}.keep must be above or below")
    z = value.get("plane_z")
    if type(z) not in (int, float) or not math.isfinite(z):
        errors.append(f"{label}.plane_z must be a finite number in world Z units")
    if type(value.get("show_guide")) is not bool:
        errors.append(f"{label}.show_guide must be true or false")
    return errors
