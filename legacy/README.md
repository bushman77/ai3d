# Legacy: parts-based character workflow

Everything here is the pre-2026-11-23 approach: Mara generated as separate
parts (body, head, upper/lower outfit, hands, equipment, and later a 10-part
anatomical split), then assembled, cut, fitted and rigged with a custom
51-bone skeleton in Blender.

It was moved here, not deleted, because the main pipeline now builds **one
watertight body mesh from several views** and rigs it with a standard
skeleton. That removes the problems this folder spent most of its code on:
double heads, garments overlapping the body, loose holster pieces, gloves
and trousers placed wrongly, and seams between parts.

Everything still runs, from the repository root:

```bash
bash legacy/build_character.sh --help
python3 -m ai3d character validate legacy/examples/space_nova/characters/mara_venn.json
python3 legacy/space_nova_pipeline/space_nova_pipeline.py --help
python3 -m unittest discover -s legacy/tests -t . -v
```

| Path | What it was |
|---|---|
| `build_character.sh` | staged modular build launcher |
| `characters/`, `cards/` | character cards, per-part generation, assembly, cut planes, staging |
| `assembly/`, `diagnostics/` | Blender cutting, thigh/holster topology diagnostics and patches |
| `rigging/`, `tools/blender/space_nova_rigs/` | skeleton prototype, custom 51-bone rig and Mara fitting |
| `tools/mara_*.py`, `config/mara_anatomy_plan.json` | 10-part "quality-first" anatomical plan |
| `pipelines/image_to_3d_v1.py` | frozen copy of the old single-image pipeline the above calls |
| `space_nova_pipeline/` | the original Space Nova launcher |
| `face_reproject.py` | front-view face texture correction for a painted GLB |
| `examples/space_nova/` | Mara cards and workflow notes (`MODULAR_WORKFLOW.md`, `CLEAN_RESTART.md`) |

Mara's original design brief is now `examples/mara/prompt.txt` and the
approved front image stays in `approved_references/`.
