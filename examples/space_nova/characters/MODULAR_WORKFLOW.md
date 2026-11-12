# Staged modular character workflow

`build_character.sh` now defaults to a **read-only plan**. A full character is
never generated, fitted and exported merely because the root script is run.

The complete appearance, clothing and equipment design is established first
in `prompt.txt` and the character card (`prompts.master`, `appearance`).
**The master design image is not yet used to condition subsequent Qwen views.**
Part reference generation currently uses independent prompts from the card.
This is a visual continuity limitation, not a solved image-splitting stage.

## Stages in the root script

Run from the repository root. Every selected component gets its own named
output folder under the chosen prefix.

```bash
cd ~/ai3d
git pull --ff-only

# Inspect plan; does not run models or write assets.
./build_character.sh --prefix mara_clean_v2

# Create only references for ALL currently defined parts.
./build_character.sh --stage reference --all-parts --prefix mara_modular_v1

# Or generate references one by one, including outfit design FIRST.
./build_character.sh --stage reference --part outfit --prefix mara_modular_v1
./build_character.sh --stage reference --part head --prefix mara_modular_v1

# Independently reconstruct detailed head, pausing after geometry.
./build_character.sh --stage shape --part head --prefix mara_modular_v1

# After visual approval of the head geometry, texture only that part.
./build_character.sh --stage paint --part head --prefix mara_modular_v1

# After painted body and head exist with the SAME run prefix:
./build_character.sh --stage preview --prefix mara_modular_v1
```

For every stage, `--dry-run` prints planned operations without running models
or writing outputs. `--resume` is implied; previously completed stages can be
reused when their inputs and options still match. `--force` is explicit and
may regenerate outputs. Use a new prefix for deliberate A/B experiments.

`--stage game --part head` exports an optimized standalone head GLB only;
it does **not** export a finished assembled character. A `--stage preview`
creates an editable Blender scene with the painted **body and head** and
approximate, reversible placement and neck cuts. It does not weld neck seams,
fit clothing, rig, or release a game asset.

## Reusing the approved clean body

The already generated `mara_clean_v2_body_front/03_shape.glb` stays intact.
To use this existing body with the new component pipeline, select the
same prefix `mara_clean_v2` when generating the separate head:

```bash
./build_character.sh --stage reference --part head --prefix mara_clean_v2
# Inspect the head reference, then explicitly continue:
./build_character.sh --stage shape --part head --prefix mara_clean_v2
# Inspect the high-detail head mesh before texture painting.
./build_character.sh --stage paint --part head --prefix mara_clean_v2
./build_character.sh --stage preview --prefix mara_clean_v2
```

The body can be used from `05_painted.glb` for the provisional preview,
but the existing painted body is not visually approved: earlier tests showed
pale panels and streaks. Do not treat this preview as production quality.

## Region and equipment separation

The current card still defines six parts: `body`, `head`, `hair`,
`outfit`, `hands`, `equipment`. **It does not yet implement separate
fitted upper/lower clothing, gloves, boots or individual props.**

`hair`, `outfit`, and `hands` have `kind=region` and currently generate
design references only. Attempting to run Hunyuan for them is rejected by
the shell unless you explicitly supply `--experimental-region-mesh`;
that opt-in produces an *unfitted experiment*, not wearable geometry.

The `equipment` part is a combined prop reference; it is not exported in
the new body+head preview. Individual pockets and holsters require later
component-card splitting and coordinate-aware fitting. That work must be
implemented and tested before adding automatic accessory assembly.

## Historical full build

The former four-stage automatic pipeline remains available **only** behind
`--legacy-full-build`:

```bash
./build_character.sh --legacy-full-build --fresh-body --prefix legacy_trial_v1
```

That mode is for comparisons, not the recommended modular workflow. It
still creates and attempts to fit the older components automatically.

`--body-only` remains a compatibility alias for
`--stage shape --part body`. Diagnostic commands
(`--diagnose`, `--thigh-prototype`, `--thigh-review`) are unchanged.
