# Space Nova integration examples

This folder is an **example consumer** of the project-independent AI3D
toolkit, not a required AI3D dependency.

`characters/mara_venn.json` illustrates a durable character card for
a full-body spaceport engineer with a unified face-and-hairstyle head,
separate upper and lower garments, hands and equipment definitions.
Its head prompt is independent of the full-body
reference to support controlled shape reconstruction experiments.

```bash
python3 -m ai3d character validate examples/space_nova/characters/mara_venn.json
```

The example specifies design intent only: it does **not** fetch images,
regenerate meshes, or join a head to a body automatically.

## Generate Mara's head reference (Qwen image only)

```bash
python3 -m ai3d character reference \
  examples/space_nova/characters/mara_venn.json \
  --part head --dry-run
# Inspect the preview, then run without --dry-run:
python3 -m ai3d character reference \
  examples/space_nova/characters/mara_venn.json \
  --part head --width 384 --height 384 --steps 12
```

The part-specific prompt deliberately excludes the full-body master prompt.
The resulting text-to-image reference may not perfectly match the original
Mara image; do not infer identity preservation. Hunyuan and Paint3D are not
launched by this command.

## Generate all Mara components, without losing completed experiments

Use a **fresh prefix** to keep the known-good individual head and existing
full-body experiments untouched:

```bash
python3 -m ai3d character generate \
  examples/space_nova/characters/mara_venn.json \
  --all --run-prefix mara_components_v1 --dry-run

python3 -m ai3d character generate \
  examples/space_nova/characters/mara_venn.json \
  --all --run-prefix mara_components_v1 --stop-after reference
```

Inspect the six images before advancing the components to shape, paint or game.
To avoid generating the head again, add `--skip head` to **all** batch
commands, then continue using the existing approved head GLB separately.
To experiment with separate garment and hand meshes, add
`--include-regions` intentionally; otherwise these remain reference-only.
Part geometry and painted assets are not automatically assembled.

## Mara's Blender body + head comparison scene

```bash
python3 -m ai3d character assemble \
  examples/space_nova/characters/mara_venn.json \
  --run-prefix mara_components_v1 --name mara_assembly_v1
blender outputs/mara_assembly_v1/preview.blend
```

This imports `mara_components_v1_body_front/05_painted.glb` and
`mara_components_v1_head_head_closeup/05_painted.glb` into separate
Blender collections. The default side-by-side staging reveals the relative
scale and geometry; it does not align the head or remove duplicated parts.
Save edits to `outputs/mara_assembly_v1/assembly.json` and rerun with
`--rebuild` to experiment with transforms non-destructively.
