# AI3D

A project-agnostic, local-first toolkit for generating and preparing 3D assets.

## Standalone CLI

From the repository root (no additional host Python packages required for
the CLI itself):

```bash
python3 -m ai3d --help
python3 -m ai3d generate --help
python3 -m ai3d inspect /path/to/model.glb
```

Generate from an image, reusing the existing separated Hunyuan, Paint3D
and Blender installations:

```bash
python3 -m ai3d generate --name example_character \\
  --image /path/to/reference.png --stop-after reference
```

All generated artifacts default to `outputs/<name>/`. The existing
`space_nova_pipeline/space_nova_pipeline.py` path remains available as a
compatibility launcher. The current pipeline continues to produce a final
`06_game.glb` filename and `game` stage for compatibility; neither requires
Space Nova to run. More expressive export naming will come later.

`inspect` performs read-only structural GLB metadata inspection; add
`--require-texture` to require UVs, image metadata, and a base-color texture
reference. This is not a full glTF conformance or visual-quality check.

## Blender round-trip validation (optional)

Use an existing **already-textured static GLB** to exercise the real Blender
optimizer without launching Qwen, Hunyuan, or Paint3D:

```bash
python3 -m ai3d inspect /path/to/painted.glb --require-texture

python3 -m ai3d validate-blender /path/to/painted.glb \\
  --name sample_blender_check --target-faces 15000 --dry-run

python3 -m ai3d validate-blender /path/to/painted.glb \\
  --name sample_blender_check --target-faces 15000
```

By default, this writes **only** to
`outputs/sample_blender_check/`, including
`blender_validated.glb`, `blender_validation.json` and
`logs/blender_validation.log`. The input file is never overwritten.
A nonempty output run directory is rejected; use a new `--name` for each
validation. This check verifies structural GLB metadata and triangle counts,
**not visual texture quality**. Inspect the resulting GLB in Blender Material
Preview from front, side and back before treating it as production-ready.

The built-in finalizer currently only targets static unrigged meshes.
Animated or armature-bearing exports are not supported by this test.

## Debugging texture baking and individual views

The mesh exists **before** texturing. Paint3D unwraps UVs, generates and
enhances selected views, projects them onto the texture atlas, then fills
uncovered texels by inpainting. Enable the upstream debug hook through AI3D
to inspect these phases without modifying third-party source files:

```bash
python3 -m ai3d generate \\
  --name texture_diagnostics \\
  --image /path/to/reference.png \\
  --shape-mesh /path/to/untextured_mesh.glb \\
  --paint-debug --stop-after paint
```

This **runs Paint3D inference**, not just a metadata check. It saves debug
images under `outputs/texture_diagnostics/paint_debug/`, including:

- `ref.png`: resized reference image actually used by the paint model
- `albedo_*.png` and `enhanced_*.png`: per-camera colors before baking
- `tex_baked.png`: UV atlas immediately after multiview projection
- `tex_trust.png`: coverage/trust mask of texels actually baked from views
- `tex_inpainted.png`: final atlas after filling missing texture areas

If a face is already malformed in `albedo_*.png`, examine reference
framing and generated views. If the views look good but `tex_baked.png`
doesn't, investigate UV projection and bake visibility. If `tex_baked.png`
looks good but `tex_inpainted.png` doesn't, investigate coverage and
inpainting. These files are generated only when `--paint-debug` is enabled.

The original Paint3D implementation resizes the reference to 512 x 512 before
creating views; a small full-body face can lose important pixels. The default
AI3D fast profile uses just two views and small render settings, which favor
6 GB GPU memory over fine detail. Make controlled single-variable changes
after reviewing the debug images.

`--paint-debug` requires running Paint3D; it cannot be combined with
`--painted-mesh`, which skips painting. All artifacts remain in the single
`outputs/` root. Existing experimental assets remain untouched.

## Reusable character cards

Version 1 includes a **permanent, project-independent character-card
template** with separate body, head, hair, clothing, hands and equipment
sections. Each part can have its own prompts, references, generation
preferences and quality gates. The source cards are editable JSON files,
never temporary generated outputs.

```bash
python3 -m ai3d character init my_character --name "My Character"
python3 -m ai3d character validate characters/my_character.json
```

New cards default to `characters/<id>.json`, a tracked source directory.
The reusable template and JSON Schema are in `ai3d/characters/`. See
[the card format guide](ai3d/characters/README.md) and the
[Mara Venn example](examples/space_nova/characters/mara_venn.json).

**Generation by part and automatic assembly are not implemented yet.** The
card establishes their persistent data contract and preserves identity,
prompts, reference metadata and intended attachment relationships.

## Project layout

- `ai3d/`: reusable Python modules, including GLB structural validation,
  a stage runner, and a Blender static-mesh optimization backend
- `pipelines/`: general-purpose orchestration (scaffold only)
- `examples/space_nova/`: consumer-specific integration example (scaffold)
- `tests/`: dependency-free unit tests
- `config/`: future source/dependency manifests
- `space_nova_pipeline/`: legacy integration, now using AI3D components
- `doctor.sh` and `install.sh`: existing dependency checks and cautious bootstrap

## Output policy

AI3D has **one default generated-file root**: `outputs/` beside this README.
Every named run is self-contained, so intermediate meshes, textures, logs,
stage manifests, reports and the final GLB are written under
`outputs/<asset_name>/`. For example:

```text
outputs/
└── example_character/
    ├── 01_reference.png
    ├── 02_cutout.png
    ├── 03_shape.glb
    ├── 04_paint_mesh.glb
    ├── 05_painted.glb
    ├── 06_game.glb
    ├── logs/
    ├── .stages/
    └── report.json
```

The legacy pipeline accepts `--output-dir PATH` to override the root, and
still accepts `--workdir PATH` as an alias for older commands. A project
checkout can be relocated without changing the default output location.

**Existing `assets/` and `pipeline_runs/` directories are legacy data.**
They are not moved, removed, or read as default output locations. They remain
Git-ignored, and existing assets may be supplied explicitly as inputs.

## Migration status

**Phase 1:** extracted filesystem helpers, GLB structural validation,
subprocess execution, stage caching and logging.

**Phase 2:** extracted material-preserving Blender finalization into
`ai3d/optimization/blender_finalize.py`. The original entry point
`space_nova_pipeline/space_nova_blender_finalize.py` remains as a
compatibility wrapper. `ai3d/optimization/blender.py` supplies a reusable
command builder. None of these changes install or modify AI backends.

The finalizer is designed for **static, already-textured GLB meshes**.
It retains UVs, imported images, and materials, but deliberately excludes
animation and non-mesh scene objects from export. Rigged/animated export is
not implemented yet. This is not an end-to-end GPU inference validation.

The legacy runner's resume fingerprint uses paths, file sizes, timestamps and
settings, not content hashes. The extracted Blender implementation is now
included as a stage dependency, so a resume may rerun final optimization once
after upgrading. Inference stages are unaffected.

**Phase 3:** pure subprocess command builders now live under
`ai3d/image/`, `ai3d/geometry/`, and `ai3d/textures/` for Qwen image
generation, Hunyuan background removal and shape/prepaint processing, and
Paint3D texture inference. Each heavyweight backend still executes in its
existing isolated runtime. No models are downloaded or imported by the host
Python test suite.

The legacy CLI also accepts optional `--sd-cli` and `--qwen-model-dir`
overrides, with the original known-working local defaults preserved.

**Phase 4:** orchestration moved into `pipelines/image_to_3d.py`, with
`python3 -m ai3d generate` and `python3 -m ai3d inspect` as
project-independent entry points. The older Space Nova launcher now delegates
to the same pipeline without duplicating generation logic. No AI weights,
CUDA environments, or runtime assets were changed.

**Phase 5:** added opt-in `ai3d validate-blender` for nondestructive
Blender round-trip validation. Real Blender execution is only possible on a
machine with Blender and a suitable textured GLB; CI covers command routing,
path safety, reports, and validation logic with a mocked subprocess.

**Phase 6:** optional `--paint-debug` exposes Paint3D's own selected
multiview images, UV bake mask and intermediate atlases. Unit tests verify
the environment and output contract without launching inference.

**Phase 7:** versioned character-card definitions, JSON Schema, source-only
templates and a standard-library `character init/validate` CLI. The worked
Mara example lives outside the project-agnostic core. Character cards contain
no live generation status or generated geometry.

## Run tests

```bash
python3 -m unittest discover -s tests -v
python3 space_nova_pipeline/space_nova_pipeline.py --help
```

No AI packages are required for these tests. For existing image-to-3D
workflows, see `space_nova_pipeline/README.md` and `DEPENDENCIES.md`.
