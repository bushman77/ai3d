# AI3D

A project-agnostic, local-first toolkit for generating and preparing 3D assets.

## Project layout

- `ai3d/`: reusable backend interfaces for image, geometry, textures,
  rigging, animation, optimization and export
- `pipelines/`: general-purpose pipeline orchestration (scaffold only)
- `examples/`: application-specific integration examples
- `tests/`: project-independent tests
- `config/`: future source/dependency manifests
- `space_nova_pipeline/`: existing working experimental implementation
- `doctor.sh` and `install.sh`: existing dependency checks and cautious bootstrap

## Current state

**This commit introduces only a directory/package structure.** It does not
migrate the working pipeline, change the Python environments, install
software, or claim new generation features.

Existing local upstream checkouts (AiGameKit and Hunyuan3D-2), model weights,
assets, and runtime outputs stay in place and outside Git tracking.
They remain independent dependencies; consult `DEPENDENCIES.md`.

The goal is reusable image-to-3D processing with configurable inputs,
backends and output formats, not a tool tied to any particular game.
