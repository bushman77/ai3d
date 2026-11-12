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

## 2026-11-11 clean-body v1 visual checkpoint failed

The first reference (mara_clean_v1) still generated waist equipment, thigh
holders, gloves and boots. The text-to-image input included an inline list
naming those unwanted items, and occupation/personality context, despite
the negating words. The v4 body card now uses "reference_mode": "visual_only"
which sends only the plain visual body reference plus camera directions.
It does not change the design brief or instructions for the head/equipment.

Do NOT reconstruct the rejected v1 reference. Generate a fresh v2 reference
with a distinct prefix to compare:

```bash
cd ~/ai3d
git pull --ff-only
python3 -m ai3d character generate \
  examples/space_nova/characters/mara_venn.json \
  --part body --stop-after reference \
  --run-prefix mara_clean_v2 --resume
xdg-open outputs/mara_clean_v2_body_front/01_reference.png
```

Only after this new reference passes visual review should you run
`./build_character.sh --body-only --prefix mara_clean_v2`.

## First run: Qwen reference then Hunyuan shape, stop

For a verified v2 reference, the body-only command is:

```bash
cd ~/ai3d
./build_character.sh --body-only --prefix mara_clean_v2
```

The script pauses after the Hunyuan shape stage without Paint3D, independent
component generation, assembly, or final GLB export.

Review:
- `outputs/mara_clean_v2_body_front/01_reference.png`
- `outputs/mara_clean_v2_body_front/03_shape.glb`

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

1. The high-detail head and body have been generated separately, painted,
   and inspected as a two-part Blender preview.
2. Mara card revision 5 replaces the combined `outfit` region with
   `upper_outfit` and `lower_outfit` region references. Generate their
   design images using `./build_character.sh --outfit-references --prefix mara_clean_v2`.
   The corresponding fitted meshes and attachment anchors are NOT implemented.
3. Continue with gloves, boots, hair and individual equipment only after
   the two garment design images pass their visual checks.
4. Paint and export wearable garments only after geometry fit, seam
   clearance and component alignment are accepted.

The active workflow is documented in `MODULAR_WORKFLOW.md`. The historical four-stage full build is now explicit:
`./build_character.sh --legacy-full-build --fresh-body --prefix legacy_trial`.
Do not use the legacy full build for the modular reconstruction.
Current `autofit.py` excludes the combined equipment mesh from export
by default, while keeping it available for manual review.

No command in this guide deletes files. Use output-folder cleanup separately
only when explicitly intended.
