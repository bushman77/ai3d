# Tests

Run the standard-library tests without installing PyTorch, Blender, or AI models:

```bash
python3 -m unittest discover -s tests -v
```

`test_glb_validation.py` covers structural GLB metadata and negative cases.
`test_pipeline_runner.py` covers stage execution, resume, force and dry-run
behavior. GPU inference and Blender integration tests remain separate future
work.
