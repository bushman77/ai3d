# Staged modular character workflow

## Removing the redundant second head

Mara's `hair / head covering` was previously a separate Qwen/Hunyuan job.
Because the hair close-up included a face, the resulting GLB depicted a second
person. Revision 6 removes this job; the `head` part now generates face, scalp
and complete tied-back hairstyle **together**. Existing saved GLBs remain
untouched, including historical standalone hair assets.

Rebuild the **existing** gallery without rerunning Qwen, Hunyuan or Paint3D:

```bash
cd ~/ai3d
git pull --ff-only
./build_character.sh --prototype-all-parts --render-only --prefix mara_complete_v1
firefox ~/ai3d/outputs/mara_complete_v1_prototypes/index.html
```

This overwrites only the HTML contact sheet and reuses (or produces) image
previews for the six remaining painted GLBs. It does not delete the old hair
folder and does not regenerate Mara's head. If an older
`_workable_character/assembly.json` contains seven parts, keep it as a
historical project: its part inventory no longer matches the active card.
Do not force a rebuild of that manifest with the changed inventory.

## Complete standalone 3D proof-of-pipeline (no review pauses)

This mode intentionally answers a different question from the staged
production workflow: **can the entire six-component pipeline run end to
end, even if the generated shapes are awkward or unfitted?**

```bash
cd ~/ai3d
./build_character.sh --prototype-all-parts
```

This is one command, with a fresh default prefix:
`mara_prototype_full_v1`. It runs the following sequence for **each**
component from the card, in card order:

1. Qwen reference image (`01_reference.png`)
2. Hunyuan3D standalone reconstruction (`03_shape.glb`)
3. Paint3D texturing (`05_painted.glb`)
4. Blender game export (`06_game.glb`)
5. Blender front, three-quarter and side renders
   (`07_preview_front.png`, `07_preview_threequarter.png`,
   `07_preview_side.png`)

The six components are `body`, `head` (face and hairstyle together),
`upper_outfit`, `lower_outfit`, `hands`, and `equipment`.
**Region meshes are deliberately included**, despite the risk that the
individual 3D outputs depict unwanted mannequin/skin/body geometry.
This is acceptable for the proof-of-pipeline run. No fitting,
alignment, assembly, or quality gates are required between stages.

After rendering, the script writes:

```text
outputs/mara_prototype_full_v1_prototype_gallery/index.html
outputs/mara_prototype_full_v1_prototype_gallery/report.json
```

Open the visual gallery with:

```bash
firefox ~/ai3d/outputs/mara_prototype_full_v1_prototype_gallery/index.html
```

Every component also has its own GLB and PNGs under
`outputs/mara_prototype_full_v1_<part>_<view>/`. The run uses serial
generation and `--resume`, so rerunning the command after a failure
reuses completed stages when the recorded inputs still match. The
render gallery also reuses up-to-date previews. For a new independent
experiment, choose `--prefix mara_prototype_full_v2`.

To inspect all commands without starting models or writing assets:

```bash
./build_character.sh --prototype-all-parts --dry-run
```

The complete run is not an automatic guarantee of success: if a backend
fails, it exits nonzero instead of claiming completion. Fix the failure
and rerun the same command to resume. Blender requires a working render
context for textured preview images; the script attempts a Workbench
fallback when a render operation raises an exception.

This mode leaves the previously generated
`mara_clean_v2_*` assets and assembly untouched.


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

Mara's card revision 6 defines **six** parts: `body`, `head` (face + hair),
`upper_outfit`, `lower_outfit`, `hands`, `equipment`. The earlier standalone
`hair / head covering` part has been removed. The head generation now produces
one face/hairstyle subject in its dedicated reference and reconstruction.
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

`upper_outfit`, `lower_outfit` and `hands` are still
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

## Proof of standalone 3D — every component (priority milestone)

The root script includes an **explicit standalone prototype mode** that does
what the normal `--all-parts` reference command does not do: it passes
`--include-regions` to the Hunyuan/Paint3D pipeline so both garment
sections and hands receive real GLB meshes. Each part is an independent
experiment; nothing is fitted to the body, rigged, or exported as a combined
character.

```bash
cd ~/ai3d
git pull --ff-only

# Preview the exact six-part plan, with no inference or Blender writes.
./build_character.sh --prototype-all-parts --prefix mara_clean_v2 --dry-run

# Execute: reuses existing body/head 05_painted.glb and approved garment
# references, generates missing meshes, then renders every component.
./build_character.sh --prototype-all-parts --prefix mara_clean_v2
```

This mode reads the current character card to discover all six parts, processes
each part serially on limited VRAM, and produces a distinct
`outputs/mara_clean_v2_<part>_<view>/05_painted.glb` plus
`preview_front.png`, `preview_side.png`, `preview_back.png`, and
`preview_threequarter.png` in that part's run directory.

The local visual contact sheet lives at:
`outputs/mara_clean_v2_prototypes/index.html`.

```bash
firefox outputs/mara_clean_v2_prototypes/index.html
```

To generate only missing clothing prototypes first, select a subset:
```bash
./build_character.sh --prototype-all-parts --prefix mara_clean_v2 \
  --part upper_outfit --part lower_outfit
```

To rerender already-produced GLBs without invoking Qwen, Hunyuan or Paint3D:
```bash
./build_character.sh --prototype-all-parts --render-only \
  --prefix mara_clean_v2
```

**Cache safety:** when `05_painted.glb` already exists and is non-empty, the
default mode *skips generation entirely for that part*. This avoids regenerating
approved body/head sources due to unrelated card edits. `--force` deliberately
regenerates and replaces cached part outputs and preview renders: use a new
`--prefix` for risky experiments.

**Limitations:** shape/texture quality can be poor; clothes can include the
mannequin; gloves/hands can be ambiguous; the equipment is still a grouped prop.
The objective here is **six independently inspectable 3D components**,
not six well-fitted wearable components. Blender Cycles CPU rendering does
not require a display or consume GPU VRAM, although it does take CPU time.

## First workable six-part character assembly

Now that `--prototype-all-parts` has generated and rendered every component,
assemble the *existing* painted meshes without running any AI models:

```bash
cd ~/ai3d
git pull --ff-only

./build_character.sh --assemble-workable --prefix mara_clean_v2 --dry-run
./build_character.sh --assemble-workable --prefix mara_clean_v2
```

This command creates a **separate** output directory,
`outputs/mara_clean_v2_workable_character/`, containing:

- `preview.blend` — Blender scene with all six independently selectable parts
- `preview.glb` — combined scene export, still containing separate objects
- `assembly.json` — editable part transforms/visibility and approximation notes
- `measurements.json` — component bounds
- `preview_front.png`, `preview_side.png`, `preview_back.png`,
  `preview_threequarter.png` — rendered fit checks

The command imports and measures each standalone GLB, applies the existing
bounds-based placement heuristic, and enables **all six components** in the
new assembled preview. It copies any compatible body/head transforms and neck
cut settings from `outputs/mara_clean_v2_assembly/assembly.json`; that
existing approved preview stays untouched. A second Blender pass exports
the fitted scene, followed by four CPU renders.

**Expect intersections and duplicate mannequin geometry**. Especially
the garment/mannequin, glove/hands and gear prototypes may contain surplus
mesh. This is a first workable *static visual prototype*, not a rigged
game-ready character. Open the resulting Blender scene, inspect, and adjust
the per-part transforms in `assembly.json` when needed.

Rerunning the command preserves manual transforms and visibility in an
existing workable manifest; `--refit` deliberately recalculates the
heuristics and reapplies compatible old body/head alignment.

```bash
blender outputs/mara_clean_v2_workable_character/preview.blend
firefox outputs/mara_clean_v2_workable_character/preview_front.png
```

No Qwen/Hunyuan/Paint3D runs, topology edits to sources, automatic rigging,
joining or seam welding occur in this operation.

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
