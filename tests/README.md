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

- `test_blender_validation.py`: safe validation-directory policy,
  dry-run and structurally checked round trips using a mocked Blender command

Real Blender GLB round trips must be run separately against a local textured
static GLB. A passing metadata check does not imply visually correct textures.

- `test_paint_diagnostics.py`: debug opt-in flag, output isolation,
  inherited-environment protection and compatibility guards

The real Paint3D debug capture requires a GPU-equipped installation and a
reference image plus untextured mesh; no inference is launched in CI.

- `test_character_cards.py`: schema version, source-card creation, parent
  cycles, reference IDs, non-overwriting persistence and CLI validation.
- `test_character_reference.py`: Qwen per-part prompt isolation, CLI dry run,
  safe output policy, resume caching and generated metadata with mocked image inference.

- `test_character_batch.py`: sequential character generation, per-part
  stages/settings, region safety, non-overwriting runs, dry-run and
  preservation of Qwen's reference cache when reused in the 3D pipeline.

- `test_character_assembly.py`: two-part preview plans, part and GLB
  selection, safe output policy, editable manifests, explicit rebuild,
  mocked Blender command execution and source-preservation checks.
