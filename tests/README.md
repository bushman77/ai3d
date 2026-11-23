# Tests

```bash
python3 -m unittest discover -s tests -v                 # pipeline, no AI or Blender needed
python3 -m unittest discover -s legacy/tests -t . -v     # legacy parts workflow
```

- `test_pipeline.py`: stage plan, view/model selection, preflight, validation, warnings
- `test_config.py`: profile loading, merging and `--set` overrides
- `test_blender_stages.py`: the real Blender scripts (prepaint, retopo + bake,
  rig, quality) on a mannequin built by `blender_fixture.py`. Skipped unless
  `blender` is on PATH or `AI3D_BLENDER` points to it. CI runs it with the
  `bpy` package.
- `test_backend_adapters.py`, `test_blender_optimization.py`,
  `test_blender_validation.py`, `test_glb_validation.py`,
  `test_pipeline_runner.py`, `test_sd_dependency.py`, `test_cli.py`:
  command builders, GLB checks, stage runner, CLI

GPU inference (Qwen, Hunyuan, Paint3D) is never launched by the tests.
