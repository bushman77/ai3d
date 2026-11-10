# AI3D

A project-agnostic, local-first toolkit for generating and preparing 3D assets.

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

## Run tests

```bash
python3 -m unittest discover -s tests -v
python3 space_nova_pipeline/space_nova_pipeline.py --help
```

No AI packages are required for these tests. For existing image-to-3D
workflows, see `space_nova_pipeline/README.md` and `DEPENDENCIES.md`.
