# Tests

Run the Python standard-library tests without installing PyTorch, Blender,
or AI model weights:

```bash
python3 -m unittest discover -s tests -v
```

- `test_glb_validation.py`: GLB structural metadata and negative cases
- `test_pipeline_runner.py`: stage execution, resume, force and dry-run
- `test_blender_optimization.py`: command construction, argument validation,
  triangle counting and legacy wrapper routing (no Blender required)

Live Blender glTF import/decimation/export and GPU inference remain separate,
hardware-dependent integration tests.
