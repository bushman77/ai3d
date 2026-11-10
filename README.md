# AI3D

A project-agnostic, local-first toolkit for generating and preparing 3D assets.

## Project layout

- `ai3d/`: reusable package modules, including GLB structural validation and
  a stage/subprocess runner; image, geometry, textures, rigging, animation,
  optimization and export backends are future integration targets
- `pipelines/`: general-purpose orchestration (scaffold only)
- `examples/space_nova/`: consumer-specific integration example (scaffold)
- `tests/`: dependency-free unit tests
- `config/`: future source/dependency manifests
- `space_nova_pipeline/`: existing working experimental implementation,
  now reusing `ai3d` core utilities without changing its CLI
- `doctor.sh` and `install.sh`: existing dependency checks and cautious bootstrap

## Migration status

**Phase 1 complete:** extracted filesystem helpers, GLB metadata validation,
subprocess execution, stage caching and logging into reusable Python modules.
The legacy `space_nova_pipeline.py` imports them, keeping its command-line
interface and existing generation stages. The source-built AI engines, virtual
environments, model weights and generated assets are not changed.

This extraction is not a complete new generation CLI. The existing runner's
resume fingerprint uses input paths, file sizes, modification times and
stage settings (not content hashes). `--dry-run` remains non-executing and
cannot yet preview every subprocess command. GLB validation is structural,
not a full glTF conformance or visual-quality check. Both limitations will
be addressed in later migrations.

## Run tests

```bash
python3 -m unittest discover -s tests -v
python3 space_nova_pipeline/space_nova_pipeline.py --help
```

No AI packages are required for these tests. For the existing image-to-3D
workflow and hardware expectations, see `space_nova_pipeline/README.md` and
`DEPENDENCIES.md`.
