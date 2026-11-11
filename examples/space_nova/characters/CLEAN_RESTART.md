# Mara clean-slate build: first checkpoint

This intentionally begins with ONE new body reference and ONE new base shape.
Do not immediately run the full 4-stage character build: it will produce
existing coarse hair/outfit/hands/equipment parts before the redesigned
attachment system has been approved.

## Design and source

- `prompt.txt` remains the original fully dressed character design brief.
- `examples/space_nova/characters/mara_venn.json` is the actual source
  of the Qwen per-part reference prompt. Its **body** prompt deliberately
  excludes belts, holsters, pouches, tools, separate boots and gloves.
- The `body` ID is retained for compatibility with current fit/assembly.
- The reference does not reconstruct an old PNG from its text. GitHub does
  not track the original generated Qwen PNG. If that image was deleted with
  `outputs/`, a new reference must be generated.
- No model weights or `.venv` files need to be deleted.

## First run: Qwen reference then Hunyuan shape, stop

After clearing `outputs/`, close Blender and run from repository root:

```bash
cd ~/ai3d
git pull --ff-only
./build_character.sh --body-only --dry-run --prefix mara_clean_v1
./build_character.sh --body-only --prefix mara_clean_v1
```

The script pauses after the Hunyuan shape stage without Paint3D, independent
component generation, assembly, or final GLB export.

Review:
- `outputs/mara_clean_v1_body_front/01_reference.png`
- `outputs/mara_clean_v1_body_front/03_shape.glb`

The Qwen reference must have a clear A-pose, uninterrupted green jumpsuit
fabric at waist/thighs, and no embedded equipment or separate props.
Review geometry in Blender's solid shading from all sides, not only the image.
If a belt, holster, pouch or missing trouser surface is present, do NOT
proceed to painting. Change the prompt/design and use a NEW prefix, keeping
failed attempts clearly identifiable.

The card still uses 384 x 576 for the full-body reference and default
20 Hunyuan shape steps for an initial controlled A/B baseline. Improve
geometry specifications only after the reference has been visually accepted.

## Later after body approval

1. Generate/validate the high-detail head with a separate close-up.
2. Split torso outfit / trousers / gloves / boots / hair / equipment into
   independently generated and fitted components. The current card still
   contains legacy `outfit`, `hands` and combined `equipment` fields;
   do not confuse these with finished modular attachments.
3. Use attachment anchors and staged approval before exporting any prop.
4. Paint and export only after body geometry and component alignment are
   accepted, then optimize and run visual regression checks.

The existing `--fresh-body --prefix mara_clean_v1` full-build invocation
can resume from the first checkpoint, but should be postponed until the
component separation work is implemented and visually checked.
Current `autofit.py` excludes the combined equipment mesh from export
by default, while keeping it available for manual review.

No command in this guide deletes files. Use output-folder cleanup separately
only when explicitly intended.
