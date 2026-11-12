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

# Or first create the separately described upper/lower outfit designs.
./build_character.sh --outfit-references --prefix mara_clean_v2
# Equivalent explicit selection:
# ./build_character.sh --stage reference --part upper_outfit --part lower_outfit --prefix mara_clean_v2

# Generate another standalone head reference only when needed.
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

The completed separately generated head and existing body assembly under
`outputs/mara_clean_v2_assembly/` remain untouched by
`--outfit-references --prefix mara_clean_v2`. Existing reference runs only
have cache metadata for their original card revision; do not rerun body/head
stages unless you intentionally want to recheck or regenerate their source.

The body can be used from `05_painted.glb` for the provisional preview,
but the existing painted body is not visually approved: earlier tests showed
pale panels and streaks. Do not treat this preview as production quality.

## Region and equipment separation

Mara's card revision 5 defines **seven** parts: `body`, `head`, `hair`,
`upper_outfit`, `lower_outfit`, `hands`, `equipment`.
The former broad `outfit` region has been replaced with **two separate
garment reference designs**:

- `upper_outfit`: fitted high collar, torso, both sleeves, wrist cuffs and
  level waist joining edge (512 × 512 design reference).
- `lower_outfit`: fitted trousers, waist joining edge, hips, knees and ankle
  cuffs (384 × 576 design reference).

Both carry the same forest-green/charcoal fabric specification, and each
has its own positive-only reference prompt, independent output folder and
visual quality gates. The master outfit still belongs to the full character
design *before* generation is split. No model-to-model image conditioning
exists yet, so exact material alignment must be checked by eye.

`hair`, `upper_outfit`, `lower_outfit` and `hands` are still
`kind=region` and currently generate design references only. The shell
rejects shape/paint/game requests for them unless you explicitly use
`--experimental-region-mesh`. That opt-in creates an **isolated, unaligned**
Hunyuan reconstruction, **not a garment fitted to Mara**. The assembly
preview still exports body and head only. For legacy assembly manifests,
the autofit module retains the earlier `outfit` staging label.

Next engineering milestone: inspect both garment references, design
body-relative garment projection/fitting and non-destructive trim/clearance
checks, then test an upper garment on a COPY of the approved body.
Do not automatically export clothing before those steps are verified.

The `equipment` part is a combined prop reference, not yet split into
individual pieces. Individual pockets, holsters and tools require future
component-card splitting and coordinate-aware fitting.

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
