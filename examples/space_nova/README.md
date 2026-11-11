# Space Nova integration examples

This folder is an **example consumer** of the project-independent AI3D
toolkit, not a required AI3D dependency.

`characters/mara_venn.json` illustrates a durable character card for
a full-body spaceport engineer with separate head, hair, outfit, hands and
equipment definitions. Its head prompt is independent of the full-body
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
To experiment with separate hair, outfit and hand meshes, add
`--include-regions` intentionally; otherwise these remain reference-only.
Part geometry and painted assets are not automatically assembled.
