# Reusable pipelines

`image_to_3d.py` orchestrates the existing reference → cutout → Hunyuan
geometry → Paint3D texturing → Blender GLB pipeline via independent
subprocess backends from `ai3d/`. It is invoked using:

```bash
python3 -m ai3d generate --help
```

All generated artifacts, stage manifests and logs default to
`outputs/<asset_name>/`; the output root is configurable. No application-
specific objects or assets are required by the orchestrator.

The existing `space_nova_pipeline/` scripts remain compatibility wrappers
for older commands. Asset-quality scoring, automated rigging, animation and
full GLB conformance checking are out of scope for the current implementation.
