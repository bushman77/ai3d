"""Persistent AI3D character-card source definitions (standard library only)."""

from copy import deepcopy
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = Path(__file__).with_name("template.json")
DEFAULT_CARDS_DIR = ROOT / "characters"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
PART_KINDS = {"mesh", "region", "attachment"}


def _slug(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def _string(value):
    return isinstance(value, str)


def _nonempty(value):
    return _string(value) and bool(value.strip())


def _string_list(value):
    return isinstance(value, list) and all(_string(v) for v in value)


def new_card(identifier: str, name: str | None = None, category: str = "humanoid") -> dict:
    """Produce an independent copy of the checked-in reusable template."""
    if not _slug(identifier):
        raise ValueError("Character ID must be lowercase snake_case")
    name = name if name is not None else identifier.replace("_", " ").title()
    if not _nonempty(name) or not _nonempty(category):
        raise ValueError("Character name and category must be nonempty")
    card = deepcopy(json.loads(TEMPLATE_PATH.read_text(encoding="utf-8")))
    card.update(id=identifier, name=name, category=category)
    return card


def validate_card(card: object) -> list[str]:
    """Validate required sections, part hierarchy and cross-references.

    Returns errors so editors and CLI clients can show multiple problems at once.
    JSON Schema tooling can additionally use the bundled schema.json.
    """
    errors = []
    if not isinstance(card, dict):
        return ["card must be a JSON object"]

    for key in ("schema_version", "id", "name", "category", "revision",
                "identity", "appearance", "prompts", "references", "parts", "assembly"):
        if key not in card:
            errors.append(f"missing field: {key}")
    if type(card.get("schema_version")) is not int or card["schema_version"] != 1:
        errors.append("schema_version must be 1")
    if not _slug(card.get("id")):
        errors.append("id must be lowercase snake_case")
    for key in ("name", "category"):
        if not _nonempty(card.get(key)):
            errors.append(f"{key} must be a nonempty string")
    if type(card.get("revision")) is not int or card["revision"] < 1:
        errors.append("revision must be a positive integer")
    if card.get("project") is not None and not _string(card["project"]):
        errors.append("project must be a string or null")

    identity = card.get("identity")
    if not isinstance(identity, dict):
        errors.append("identity must be an object")
    else:
        if not _string(identity.get("role")):
            errors.append("identity.role must be a string")
        for field in ("personality_traits", "continuity_rules"):
            if not _string_list(identity.get(field)):
                errors.append(f"identity.{field} must be an array of strings")

    appearance = card.get("appearance")
    if not isinstance(appearance, dict):
        errors.append("appearance must be an object")
    else:
        for field in ("style", "silhouette"):
            if not _string(appearance.get(field)):
                errors.append(f"appearance.{field} must be a string")
        if not _string_list(appearance.get("recognition_traits")):
            errors.append("appearance.recognition_traits must be an array of strings")

    prompts = card.get("prompts")
    if not isinstance(prompts, dict):
        errors.append("prompts must be an object")
    else:
        if not all(_string(prompts.get(k)) for k in ("master", "negative")):
            errors.append("prompts.master and prompts.negative must be strings")
        views = prompts.get("reference_views")
        if not isinstance(views, dict) or not all(_string(k) and _string(v) for k,v in views.items()):
            errors.append("prompts.reference_views must map names to prompt strings")

    references = card.get("references")
    ref_ids = set()
    if not isinstance(references, list):
        errors.append("references must be an array")
    else:
        for index, ref in enumerate(references):
            tag = f"references[{index}]"
            if not isinstance(ref, dict):
                errors.append(f"{tag} must be an object")
                continue
            ref_id = ref.get("id")
            if not _slug(ref_id):
                errors.append(f"{tag}.id is invalid")
            elif ref_id in ref_ids:
                errors.append(f"duplicate reference: {ref_id}")
            else:
                ref_ids.add(ref_id)
            if not _nonempty(ref.get("path")) or not _string(ref.get("purpose")):
                errors.append(f"{tag} requires path and purpose")

    parts = card.get("parts")
    part_ids = {}
    if not isinstance(parts, list) or not parts:
        errors.append("parts must be a nonempty array")
    else:
        for index, part in enumerate(parts):
            tag = f"parts[{index}]"
            if not isinstance(part, dict):
                errors.append(f"{tag} must be an object")
                continue
            part_id = part.get("id")
            if not _slug(part_id):
                errors.append(f"{tag}.id is invalid")
            elif part_id in part_ids:
                errors.append(f"duplicate part: {part_id}")
            else:
                part_ids[part_id] = part
            if not _nonempty(part.get("label")) or not isinstance(part.get("kind"), str) or part["kind"] not in PART_KINDS:
                errors.append(f"{tag} needs a label and kind (mesh, region, attachment)")
            parent = part.get("parent")
            if parent is not None and not _slug(parent):
                errors.append(f"{tag}.parent must be a part id or null")
            if part.get("attachment") is not None and not _string(part["attachment"]):
                errors.append(f"{tag}.attachment must be a string or null")
            refs = part.get("reference_ids")
            if not _string_list(refs):
                errors.append(f"{tag}.reference_ids must be an array of strings")
            else:
                if len(refs) != len(set(refs)):
                    errors.append(f"{tag}.reference_ids has duplicates")
                for ref_id in refs:
                    if ref_id not in ref_ids:
                        errors.append(f"{tag} has unknown reference: {ref_id}")
            ref_view = part.get("reference_view")
            if ref_view is not None and (not _string(ref_view) or not ref_view.strip()):
                errors.append(f"{tag}.reference_view must be a nonempty string")
            elif ref_view is not None and isinstance(prompts, dict) and ref_view not in prompts.get("reference_views", {}):
                errors.append(f"{tag}.reference_view is not defined in prompts.reference_views")
            pp = part.get("prompts")
            if not isinstance(pp, dict) or not all(_string(pp.get(k)) for k in ("geometry", "texture")):
                errors.append(f"{tag}.prompts requires geometry and texture strings")
            if isinstance(pp, dict):
                for optional_prompt in ("reference", "negative"):
                    if optional_prompt in pp and not _string(pp[optional_prompt]):
                        errors.append(f"{tag}.prompts.{optional_prompt} must be a string")
            gen = part.get("generation")
            if not isinstance(gen, dict):
                errors.append(f"{tag}.generation must be an object")
            else:
                if gen.get("reference_mode") not in (None, "contextual", "visual_only"):
                    errors.append(f"{tag}.generation.reference_mode must be contextual or visual_only")
                for k in ("geometry_backend", "texture_backend"):
                    if gen.get(k) is not None and not _nonempty(gen[k]):
                        errors.append(f"{tag}.generation.{k} must be string or null")
                for k in ("shape_steps", "target_triangles", "view_resolution", "reference_width", "reference_height"):
                    val = gen.get(k)
                    if val is not None and (type(val) is not int or val < 1):
                        errors.append(f"{tag}.generation.{k} must be positive or null")
            if not _string_list(part.get("quality_gates")):
                errors.append(f"{tag}.quality_gates must be an array of strings")

        for part_id, part in part_ids.items():
            parent = part.get("parent")
            if parent is not None and parent not in part_ids:
                errors.append(f"{part_id} has unknown parent: {parent}")
            seen = {part_id}
            while isinstance(parent, str) and parent in part_ids:
                if parent in seen:
                    errors.append(f"cycle in part hierarchy: {part_id}")
                    break
                seen.add(parent)
                parent = part_ids[parent].get("parent")

    assembly = card.get("assembly")
    if not isinstance(assembly, dict):
        errors.append("assembly must be an object")
    else:
        for field in ("units", "up_axis", "forward_axis", "rest_pose"):
            if not _string(assembly.get(field)):
                errors.append(f"assembly.{field} must be a string")
        if "rigging_required" in assembly and not isinstance(assembly["rigging_required"], bool):
            errors.append("assembly.rigging_required must be boolean")
    if "notes" in card and not _string_list(card["notes"]):
        errors.append("notes must be an array of strings")
    return errors


def load_card(path: Path) -> dict:
    """Load a validated saved definition, reporting friendly errors."""
    path = Path(path).expanduser()
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc
    problems = validate_card(card)
    if problems:
        raise RuntimeError(f"Invalid card {path}:\n  - " + "\n  - ".join(problems))
    return card


def save_new_card(card: dict, path: Path) -> Path:
    """Validate and create a durable definition; never overwrite a saved card."""
    problems = validate_card(card)
    if problems:
        raise RuntimeError("Invalid character card:\n  - " + "\n  - ".join(problems))
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(card, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path
