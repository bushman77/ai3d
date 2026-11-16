#!/usr/bin/env python3
"""Create a non-destructive, reference-locked anatomical Mara card.

Run from ~/ai3d. This stage writes source definitions only: no GPU inference,
image modification, generated meshes, or changes to the existing character card.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

EXPECTED_MASTER_SHA256 = "144d06916502ecb524e4113f8bc11b9ab80bfa6714290773a7046d23bd4e2791"
DEFAULT_CARD = Path("examples/space_nova/characters/mara_venn.json")
DEFAULT_IMAGE = Path("approved_references/mara_body_front_approved.png")
DEFAULT_TARGET = Path("examples/space_nova/characters/mara_venn_anatomical.json")
DEFAULT_PLAN = Path("config/mara_anatomy_plan.json")

# Deliberately define separate left/right mesh entities, not a single full-body
# mesh described using anatomical labels.
COMPONENTS = [
    ("torso_pelvis", "Torso and pelvis", None, "torso", "the collar-to-hip torso and pelvis, with clean neck, shoulder and hip joining borders", "neutral front, T-pose alignment"),
    ("left_arm", "Left arm", "torso_pelvis", "left_shoulder", "Mara's LEFT upper and lower arm from shoulder to wrist; shoulder and wrist joining edges visible, no hand or torso", "anatomical left, fully extended horizontally"),
    ("right_arm", "Right arm", "torso_pelvis", "right_shoulder", "Mara's RIGHT upper and lower arm from shoulder to wrist; shoulder and wrist joining edges visible, no hand or torso", "anatomical right, fully extended horizontally"),
    ("left_hand", "Left hand", "left_arm", "left_wrist", "Mara's LEFT hand and fingers, separate from the sleeve, five anatomically distinct digits", "anatomical left, palm orientation to match the approved reference"),
    ("right_hand", "Right hand", "right_arm", "right_wrist", "Mara's RIGHT hand and fingers, separate from the sleeve, five anatomically distinct digits", "anatomical right, palm orientation to match the approved reference"),
    ("left_leg", "Left leg", "torso_pelvis", "left_hip", "Mara's LEFT thigh, knee and calf ending at the ankle, separate from the pelvis and foot", "anatomical left, straight leg, forward knee"),
    ("right_leg", "Right leg", "torso_pelvis", "right_hip", "Mara's RIGHT thigh, knee and calf ending at the ankle, separate from the pelvis and foot", "anatomical right, straight leg, forward knee"),
    ("left_foot", "Left foot", "left_leg", "left_ankle", "Mara's LEFT foot in its industrial boot, independent from the lower leg", "anatomical left, sole flat, toes forward"),
    ("right_foot", "Right foot", "right_leg", "right_ankle", "Mara's RIGHT foot in its industrial boot, independent from the lower leg", "anatomical right, sole flat, toes forward"),
]


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def new_part(part_id: str, label: str, parent: str | None, attachment: str, subject: str, view_text: str, base: dict) -> dict:
    generation = copy.deepcopy(base.get("generation", {}))
    generation.update({
        "reference_width": 512,
        "reference_height": 512,
        "reference_mode": "visual_only",
        # NOTE: existing AI3D generators ignore these custom metadata fields;
        # the plan's GPU gate remains closed until the adapter is implemented.
        "approved_master_required": True,
    })
    return {
        "id": part_id,
        "label": label,
        "kind": "mesh",
        "parent": parent,
        "attachment": attachment if parent is not None else None,
        "reference_ids": ["mara_master_front"],
        "prompts": {
            "reference": (
                f"Isolated orthographic reconstruction reference of only {subject}. "
                "Match the identity, material boundaries, proportions and exact colors of the approved "
                "Mara Venn master reference. Keep the full component and both joining borders visible. "
                "A single component, neutral gray studio backdrop, not a complete person. "
                "No extra arms, fingers, legs, hands, heads, props or duplicate geometry."
            ),
            "geometry": f"Reconstruct only {subject}. Preserve clean anatomical joint borders; do not generate neighboring components.",
            "texture": "Match the approved Mara reference: forest-green and charcoal engineering fabric where applicable, realistic material transitions and no incidental equipment.",
            "negative": "No full human body, duplicate component, detached extra geometry, accessories, watermark or background objects.",
        },
        "reference_view": f"{part_id}_detail",
        "generation": generation,
        "quality_gates": [
            "Reference crop or image-conditioned edit must be verified against the approved master PNG before inference",
            "One and only one anatomically correct component is present",
            "Correct anatomical side; no unrequested mirror replacement",
            "Joint boundaries are preserved and measured for later attachment",
            "Inspect mesh silhouette and joining surfaces before texturing",
        ],
        "notes": f"{view_text}. Draft geometry definition only. Existing text-to-image generation does not preserve identity from master PNG. No automatic fitting or seam welding yet.",
    }


def build(source: dict, image_path: Path, digest: str) -> tuple[dict, dict]:
    old_parts = {part["id"]: copy.deepcopy(part) for part in source["parts"]}
    required = {"body", "head", "upper_outfit", "lower_outfit", "hands", "equipment"}
    if not required.issubset(old_parts):
        raise ValueError(f"Unexpected source card; missing parts: {sorted(required - old_parts.keys())}")
    if source.get("id") != "mara_venn":
        raise ValueError("This migration only supports the Mara Venn card")

    card = copy.deepcopy(source)
    card["revision"] = int(source.get("revision", 1)) + 1
    card["references"] = [r for r in card.get("references", []) if r.get("id") != "mara_master_front"]
    card["references"].append({
        "id": "mara_master_front",
        "path": str(image_path),
        "purpose": "Approved Qwen character identity and anatomical proportion anchor",
        "view": "front",
        "notes": f"Immutable approved source. SHA-256: {digest}; do not regenerate or overwrite.",
    })
    card["prompts"]["reference_views"].update({
        f"{part_id}_detail": f"Single component only: {view_text}. Maintain master image identity and T-pose coordinate frame."
        for part_id, _label, _parent, _attach, _subject, view_text in COMPONENTS
    })

    parts = []
    body_base = old_parts["body"]
    parts.append(new_part(*COMPONENTS[0], body_base))
    head = old_parts["head"]
    head["parent"] = "torso_pelvis"
    head["reference_ids"] = sorted(set(head.get("reference_ids", []) + ["mara_master_front"]))
    head["notes"] = head.get("notes", "") + " Master PNG is an identity anchor; an image-conditioned reference stage is still required."
    parts.append(head)
    for entry in COMPONENTS[1:]:
        parts.append(new_part(*entry, body_base))
    for key in ("upper_outfit", "lower_outfit", "equipment"):
        part = old_parts[key]
        part["parent"] = "torso_pelvis"
        part["reference_ids"] = sorted(set(part.get("reference_ids", []) + ["mara_master_front"]))
        parts.append(part)
    card["parts"] = parts
    card["assembly"]["rigging_required"] = True
    card["assembly"]["notes"] = (
        "Anatomical T-pose, metres, +Z up and -Y forward. Modular component frames "
        "and joining landmarks must be established and reviewed before rigging. "
        "Existing two-part body/head assembly is incompatible with this card until adapted."
    )
    card.setdefault("notes", []).append(
        "Reference locked to the original approved Qwen image; do not invoke the text-only reference stage for component production."
    )
    plan = {
        "version": 1,
        "card_id": "mara_venn",
        "original_card": str(DEFAULT_CARD),
        "source_image": str(image_path),
        "source_sha256": digest,
        "component_ids": [part["id"] for part in parts if part["kind"] == "mesh"],
        "reference_method": "pending_verified_crops_or_image_conditioned_edit",
        "component_crops": {part["id"]: None for part in parts if part["kind"] == "mesh"},
        "gpu_generation_permitted": False,
        "blockers": [
            "Create and inspect component masks/crops from approved master; preserve exact aspect ratio and origin",
            "Implement and test image-conditioned reference consumption instead of the current text-only Qwen path",
            "Establish shared component scale, landmarks, and seam-fit validation",
            "Adapt existing two-part Blender preview to a multi-component assembly",
        ],
    }
    return card, plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", type=Path, default=DEFAULT_CARD)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if not args.card.is_file() or not args.image.is_file():
            raise ValueError("Source Mara card and approved reference image must exist")
        digest = sha256(args.image)
        if digest != EXPECTED_MASTER_SHA256:
            raise ValueError("Approved reference SHA-256 differs from expected original; no files written")
        source = json.loads(args.card.read_text(encoding="utf-8"))
        card, plan = build(source, args.image, digest)
        # Scripts invoked as `python3 tools/foo.py` need the repository root
        # on sys.path in order to import the local package.
        repo_root = Path(__file__).resolve().parents[1]
        if (repo_root / "ai3d").is_dir() and str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        # Validate against the actual repository's authoritative schema checks.
        from ai3d.characters.card import validate_card
        issues = validate_card(card)
        if issues:
            raise ValueError("Invalid modular card: " + "; ".join(issues))
        print(f"Verified master image: {args.image} ({digest[:12]}…)")
        print("Independent mesh parts: " + ", ".join(plan["component_ids"]))
        print("GPU generation: BLOCKED until image-conditioning + fitting are implemented")
        if args.dry_run:
            print(f"Would create: {args.output} and {args.plan}")
            return 0
        if args.output.resolve() == args.plan.resolve():
            raise ValueError("Card and plan paths cannot be identical")
        if args.output.exists() or args.plan.exists():
            raise ValueError("Output exists; refusing overwrite (source and approved image remain unchanged)")
        for path in (args.output, args.plan):
            path.parent.mkdir(parents=True, exist_ok=True)
        written = []
        try:
            for path, value in ((args.output, card), (args.plan, plan)):
                with path.open("x", encoding="utf-8") as handle:
                    json.dump(value, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                written.append(path)
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise
        print(f"Created: {args.output}\nCreated: {args.plan}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
