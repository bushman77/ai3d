"""Qwen reference generation for one component of a persistent character card.

Only image generation is implemented here; mesh reconstruction and assembly
remain separate future stages. Requires no AI libraries in the host Python.
"""

import hashlib
import json
from pathlib import Path
import subprocess

from ai3d.common import ensure_file, resolve
from ai3d.image.qwen import build_qwen_command
from ai3d.output import DEFAULT_OUTPUT_ROOT, run_directory
from ai3d.pipeline_runner import Runner

MODEL_FILES = (
    "qwen-image-2512-Q3_K_M.gguf",
    "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
    "qwen_image_vae.safetensors",
)


def select_part_and_view(card: dict, part_id: str, view: str | None = None) -> tuple[dict, str]:
    parts = {part["id"]: part for part in card["parts"]}
    if part_id not in parts:
        raise RuntimeError(
            f"Character {card['id']} has no part {part_id!r}; "
            f"available: {', '.join(parts)}"
        )
    part = parts[part_id]
    selected_view = view or part.get("reference_view") or "front"
    view_prompt = card["prompts"]["reference_views"].get(selected_view, "")
    if not isinstance(view_prompt, str) or not view_prompt.strip():
        raise RuntimeError(
            f"No reference instructions for view {selected_view!r}; "
            "add prompts.reference_views entry or choose --view"
        )
    return part, selected_view


def compose_reference_prompt(card: dict, part: dict, view: str) -> str:
    """Use explicit part framing, not the potentially conflicting master prompt."""
    prompts = part["prompts"]
    specific = prompts.get("reference", "").strip()
    if not specific:
        raise RuntimeError(
            f"Part {part['id']!r} needs a dedicated prompts.reference string"
        )
    # A visual-only reference deliberately excludes role, personality and
    # inline "Avoid: ..." lists. Some text-to-image backends render objects
    # named in negated phrases; keep such constraints in the source card for
    # review rather than feeding their nouns to a positive-only prompt.
    if part.get("generation", {}).get("reference_mode") == "visual_only":
        return "\n".join([
            "Clean studio visual reference for 3D reconstruction.",
            specific,
            "View: " + card["prompts"]["reference_views"][view].strip(),
            "",
        ])

    ident, appearance = card["identity"], card["appearance"]
    negative = prompts.get("negative", "").strip() or card["prompts"]["negative"].strip()
    lines = [
        "Single-character studio reference for accurate 3D asset reconstruction.",
        f"Character: {card['name']}.",
        f"Target component: {part['label']}.",
    ]
    for label, value in (
        ("Role", ident.get("role", "")),
        ("Species", ident.get("species", "")),
        ("Age group", ident.get("age_group", "")),
        ("Visual style", appearance.get("style", "")),
    ):
        if isinstance(value, str) and value.strip():
            lines.append(f"{label}: {value.strip()}.")
    # Face/personality cues can make isolated tools or garments sprout a
    # person. Apply facial identity constraints only to facial/primary meshes.
    if part["kind"] == "mesh" or part.get("parent") == "head":
        if ident.get("personality_traits"):
            lines.append("Personality: " + ", ".join(ident["personality_traits"]) + ".")
        if appearance.get("recognition_traits"):
            lines.append("Identity cues: " + "; ".join(appearance["recognition_traits"]) + ".")
    lines.extend([
        "Component reference: " + specific,
        "View: " + card["prompts"]["reference_views"][view].strip(),
    ])
    if negative:
        lines.append("Avoid: " + negative)
    return "\n".join(lines) + "\n"


def run_reference(
    card: dict, card_path: Path, *, part_id: str, view: str | None = None,
    name: str | None = None, output_dir: Path = DEFAULT_OUTPUT_ROOT,
    sd_cli: Path, model_dir: Path, width: int = 384, height: int = 384,
    steps: int = 12, ram_limit: str = "10G", swap_limit: str = "1G",
    resume: bool = False, force: bool = False, dry_run: bool = False,
) -> Path:
    """Generate a standalone PNG reference under outputs/<run-name>/."""
    if min(width, height, steps) <= 0:
        raise RuntimeError("Width, height and steps must be positive")
    part, selected_view = select_part_and_view(card, part_id, view)
    prompt = compose_reference_prompt(card, part, selected_view)
    home = run_directory(name or f"{card['id']}_{part_id}_{selected_view}", output_dir)
    reference = home / "01_reference.png"
    prompt_file = home / "reference_prompt.txt"
    manifest_file = home / "reference_manifest.json"

    if home.is_symlink():
        raise RuntimeError(f"Refusing run-directory symlink: {home}")
    if home.exists() and not home.is_dir():
        raise RuntimeError(f"Output run path is not a directory: {home}")
    if home.exists() and not (resume or force or dry_run):
        raise RuntimeError(
            f"Output run exists: {home}; choose --name or pass --resume/--force"
        )
    for path in (reference, prompt_file, manifest_file, home / "logs", home / ".stages"):
        if path.is_symlink():
            raise RuntimeError(f"Refusing output symlink: {path}")

    executable = resolve(sd_cli)
    weights_dir = resolve(model_dir)
    weights = [weights_dir / file for file in MODEL_FILES]
    command = build_qwen_command(
        executable, weights_dir, prompt, reference, width=width,
        height=height, steps=steps, ram_limit=ram_limit, swap_limit=swap_limit,
    )
    print(f"Character: {card['name']} | part: {part_id} | view: {selected_view}")
    print(f"Output: {reference}")
    if dry_run:
        print("--- Qwen prompt ---\n" + prompt)
        print("--- Command (not executed) ---")
        print(subprocess.list2cmdline(command))
        print("Dry run; no files generated.")
        return reference

    ensure_file(card_path, "Character card")
    ensure_file(executable, "Qwen sd-cli")
    for weight in weights:
        ensure_file(weight, "Qwen model weight")

    home.mkdir(parents=True, exist_ok=True)
    runner = Runner(home, resume=resume, force=force, dry=False)
    options = {
        "part": part_id, "view": selected_view,
        "width": width, "height": height, "steps": steps,
        "ram_limit": ram_limit, "swap_limit": swap_limit,
        "model_dir": str(weights_dir), "sd_cli": str(executable),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    runner.run(
        "reference", [card_path, executable, *weights], [reference], options,
        lambda: runner.command("reference", command, cwd=executable.parent),
    )
    prompt_file.write_text(prompt, encoding="utf-8")
    manifest = {
        "character_id": card["id"], "character_name": card["name"],
        "card_source": str(resolve(card_path)), "card_revision": card["revision"],
        "card_sha256": hashlib.sha256(
            json.dumps(card, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "part": part_id, "view": selected_view, "backend": "qwen-sd-cli",
        "reference_image": reference.name, "prompt_file": prompt_file.name,
        "settings": options, "quality_gates": part["quality_gates"],
        "generation": runner.timing.get("reference"),
    }
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Reference generated: {reference}")
    print(f"Manifest: {manifest_file}")
    return reference
