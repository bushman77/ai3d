#!/usr/bin/env python3
"""Install conservative master-reference safety gates in the local AI3D pipeline.

Runs from ~/ai3d or from any location with --root. Does not touch approved
reference images, generated assets, model weights or character-card JSON.

This is intentionally a fail-closed temporary guard. The later image-
conditioned reference adapter must replace this restriction after testing.
"""

from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import shutil
import sys
import tempfile

MARK = "MARA_APPROVED_IMAGE_GUARD_V1"

BATCH_ANCHOR = '''    """Generate one character's parts *serially* to respect limited VRAM."""\n'''
BATCH_INJECT = '''    """Generate one character's parts *serially* to respect limited VRAM."""
    # MARA_APPROVED_IMAGE_GUARD_V1: never run text-only inference on locked cards.
    if not dry_run and any(
        part.get("generation", {}).get("approved_master_required") is True
        for part in card.get("parts", [])
    ):
        raise RuntimeError(
            "Approved-master anatomical card is LOCKED: implement and verify "
            "image-conditioned component references before GPU generation. "
            "Use --dry-run for planning."
        )
'''

REF_ANCHOR = '''    """Generate a standalone PNG reference under outputs/<run-name>/."""\n'''
REF_INJECT = '''    """Generate a standalone PNG reference under outputs/<run-name>/."""
    # MARA_APPROVED_IMAGE_GUARD_V1: do not replace the canonical Qwen identity.
    if not dry_run and any(
        part.get("generation", {}).get("approved_master_required") is True
        for part in card.get("parts", [])
    ):
        raise RuntimeError(
            "Approved-master anatomical card is LOCKED: the current Qwen "
            "reference command is text-to-image only, not image-conditioned. "
            "Use --dry-run for planning."
        )
'''

SHELL_ANCHOR = '''"$PYTHON" -m ai3d character validate "$CARD"\n'''
SHELL_INJECT = '''"$PYTHON" -m ai3d character validate "$CARD"
# MARA_APPROVED_IMAGE_GUARD_V1: keep the approved-master anatomy card read-only
# until the reference adapter, geometry alignment and rigging are implemented.
# This safeguards wrapper-specific paths as well as Python batch/reference paths.
if (( ! DRY_RUN )); then
  "$PYTHON" - "$CARD" "${MODULAR_STAGE:-plan}" \\
    "$RIG_PROTOTYPE" "$ASSEMBLE_WORKABLE" "$PROTOTYPE_ALL" \\
    "$LEGACY_FULL" "$OUTFIT_REFERENCES" "$START_TPOSE" "$BODY_ONLY" <<'PY_GUARD'
import json
import sys
card_file, stage, *mode_flags = sys.argv[1:]
with open(card_file, encoding="utf-8") as file:
    card = json.load(file)
locked = any(
    part.get("generation", {}).get("approved_master_required") is True
    for part in card.get("parts", [])
)
if locked and (stage != "plan" or any(value == "1" for value in mode_flags)):
    raise SystemExit(
        "ERROR: Approved-master anatomical card is LOCKED. "
        "Only --stage plan and --dry-run are permitted until "
        "verified image-conditioned references and fitting are implemented."
    )
PY_GUARD
fi
'''

PATCHES = (
    ("legacy/characters/batch.py", BATCH_ANCHOR, BATCH_INJECT),
    ("legacy/characters/reference.py", REF_ANCHOR, REF_INJECT),
    ("build_character.sh", SHELL_ANCHOR, SHELL_INJECT),
)


def prepare(root: Path):
    result = []
    for relative, anchor, injected in PATCHES:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Required source not found: {path}")
        original = path.read_text(encoding="utf-8")
        if MARK in original:
            if injected not in original:
                raise RuntimeError(f"Guard marker exists but differs: {path}")
            result.append((path, original, original, "already installed"))
            continue
        count = original.count(anchor)
        if count != 1:
            raise RuntimeError(f"Expected one insertion anchor, found {count}: {path}")
        modified = original.replace(anchor, injected, 1)
        result.append((path, original, modified, "to install"))
    return result


def atomic_write(path: Path, content: str):
    # Preserve the script's executable mode when replacing it.
    mode = path.stat().st_mode
    fd, name = tempfile.mkstemp(prefix=".mara-guard-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        modifications = prepare(root)
        for path, old, new, state in modifications:
            print(f"{path.relative_to(root)}: {state}")
            if args.dry_run and old != new:
                print("".join(difflib.unified_diff(
                    old.splitlines(True), new.splitlines(True),
                    fromfile=str(path.relative_to(root)),
                    tofile=str(path.relative_to(root)) + " (guarded)",
                )))
        if args.dry_run:
            print("DRY RUN: Nothing was changed.")
            return 0

        changed = [(p, old, new) for p, old, new, _ in modifications if old != new]
        if not changed:
            print("Guard already installed. Nothing changed.")
            return 0
        backup = root / "backups" / "mara_anatomy_safety_gate_v1"
        if backup.exists():
            raise RuntimeError(
                f"Backup directory already exists: {backup}. "
                "Refusing to overwrite earlier backups."
            )
        backup.mkdir(parents=True)
        for path, original, _new in changed:
            target = backup / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

        try:
            for path, _original, new in changed:
                atomic_write(path, new)
        except Exception:
            for path, original, _new in changed:
                atomic_write(path, original)
            raise
        print(f"Backup preserved at {backup}")
        print("Installed guards in Python batch/reference and shell wrapper.")
        print("No AI model, generated output, character card or image was modified.")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
