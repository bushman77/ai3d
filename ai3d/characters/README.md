# AI3D character cards — version 1

Character cards are **permanent, human-editable source definitions** for
one character and its independently managed parts. They are project-agnostic
and use JSON so they can be consumed without installing additional packages.

## Create a card

```bash
cd ~/ai3d
python3 -m ai3d character init my_character --name "My Character"
python3 -m ai3d character validate characters/my_character.json
```

Use `--category android` or another category as needed, and edit the
starter parts to match your character. Use `--output /path/to/card.json` to
place the card in any repository. Existing cards are **never overwritten**.

The original starter lives at `ai3d/characters/template.json`. Its schema is
`ai3d/characters/schema.json` (JSON Schema Draft 2020-12), which editors or
external validators can use. AI3D's built-in validator needs only Python's
standard library, and also checks parent cycles and duplicate IDs.

## Sections

| Section | Purpose |
|---|---|
| `schema_version` | Format version; future migrations can be explicit |
| `id`, `name`, `category`, `project`, `revision` | Identity and source revision |
| `identity` | Role, species, personality, backstory, consistency rules |
| `appearance` | Style, silhouette, face, hair, clothing, palette, recognizability |
| `prompts` | Master and negative prompts, plus per-view prompt instructions |
| `references` | Optional named image references, with view and purpose metadata |
| `parts` | Body/head/hair/outfit/hands/equipment or any custom component graph |
| `assembly` | Intended units, axes, rest pose, rigging and attachment notes |
| `provenance`, `notes` | Optional authorship, licensing, design notes |

A part defines its ID, label, kind, parent part, intended attachment,
reference IDs, separate geometry and texture prompts, optional generation
preferences, human quality gates and notes.

- `mesh`: intended separate generated geometry, e.g. body or head
- `region`: a logical part of a larger mesh, e.g. hair or clothing
- `attachment`: detachable accessory or part anchored to a parent

These are **design classifications**, not automatic Blender operations.
Parent links must refer to another part and cannot form cycles. Attachment
strings are descriptive until an explicit assembly system exists.

The template starts with six editable parts, but a creature, robot or other
character may have any valid component set. You can add `tail`, `wings`,
`helmet`, `antennae`, or remove irrelevant sections.

### Reference images

Example entry (paths are descriptive; validation doesn't require the image
to exist yet):

```json
{
  "id": "head_front",
  "path": "images/head_front.png",
  "purpose": "Head geometry reference",
  "view": "front",
  "notes": "Same identity as full-body reference"
}
```

Then add `"head_front"` to the head part's `reference_ids`.
Source-image storage and paths are a project decision: large images, models and
generated output remain Git-ignored under AI3D's existing rules.

## Source versus generated output

Version-control the **card definitions** in `characters/` or your consuming
project. Generated images, meshes, stages, logs, metrics, approvals and runtime
history belong under the already-established `outputs/` root. They must not
be mixed into a persistent design card.

The CLI supports **`character init`**, **`character validate`** and
**`character reference`**. The last command creates an image reference for a
selected part using the existing Qwen/stable-diffusion.cpp adapter.

### Qwen component reference generation

Give each part an image-specific `prompts.reference` string plus optional
`prompts.negative` override and `reference_view` pointing to a key in the
character's `prompts.reference_views`. The reference prompt is distinct from
the part's downstream `prompts.geometry` and `prompts.texture` specifications.

```bash
cd ~/ai3d
python3 -m ai3d character reference \
  examples/space_nova/characters/mara_venn.json \
  --part head --dry-run
```

Inspect the composed prompt. To generate the image with Qwen on a machine
with installed weights and an available CUDA backend, remove `--dry-run`:

```bash
python3 -m ai3d character reference \
  examples/space_nova/characters/mara_venn.json \
  --part head --width 384 --height 384 --steps 12
```

The default output is `outputs/mara_venn_head_head_closeup/`, containing
`01_reference.png`, `reference_prompt.txt`, `reference_manifest.json`,
stage metadata and logs. Use `--name alternate_head_trial` for another run,
`--resume` to reuse an unchanged successful run, or `--force` to explicitly
regenerate an existing one. No default command silently overwrites an output
directory. `--view`, `--sd-cli`, `--qwen-model-dir`, `--output-dir`,
`--ram`, and `--swap` are available for explicit overrides.

**Important:** The card's `prompts.master` may describe an entirely different
framing (such as a full-body A-pose), so the reference stage deliberately uses
the part-specific reference instructions instead. A nonempty part
`prompts.negative` overrides the master negative prompt to avoid contradictory
framing constraints. Blank part reference prompts are refused.

The stage uses Qwen **text-to-image**. It describes the same character but
cannot guarantee pixel-identical identity with an earlier picture. Passing a
previous source image for image-conditioned identity preservation is a
future workflow; do not confuse a newly generated head reference with a crop
of the original character.

## Multi-part generation from a character card

The `character generate` command drives each selected part **serially** to
avoid multiple GPU processes competing for the same 6 GB graphics card.
It reuses the existing Qwen reference, Hunyuan shape, Paint3D texture and
Blender finalization stages. Each part gets an independent
`outputs/<prefix>_<part>_<view>/` folder with logs and stage caches.

**Preview every part without touching the GPU or filesystem:**

```bash
cd ~/ai3d
python3 -m ai3d character generate \
  examples/space_nova/characters/mara_venn.json \
  --all --run-prefix mara_components_v1 --dry-run
```

**Produce every component's reference image first:**

```bash
python3 -m ai3d character generate \
  examples/space_nova/characters/mara_venn.json \
  --all --run-prefix mara_components_v1 --stop-after reference
```

Inspect the images and correct prompts before expensive 3D generation.
Then continue from the **same run prefix**:

```bash
python3 -m ai3d character generate \
  examples/space_nova/characters/mara_venn.json \
  --all --run-prefix mara_components_v1 --stop-after shape --resume
```

Then use `--stop-after paint --resume` and finally
`--stop-after game --resume` for approved parts. For debug UV atlases,
add `--paint-debug` to the paint stage.

With `--all`, the **mesh** and **attachment** components progress to
the selected stage. A logical **region** (for example clothing or hair)
generates its reference PNG but does not become a separate mesh by default.
Use `--include-regions` to explicitly experiment with independent geometry
for every region. Such regions may contain additional geometry, require
manual separation, or be incompatible with automatic assembly.

Useful controls:

- `--part head` (repeat to select several parts) instead of `--all`
- `--skip head` to preserve an already-approved head from a previous run
- `--run-prefix mara_components_v1` to isolate new experiments from old runs
- `--resume` to reuse unchanged stages and continue an interrupted pipeline
- `--force` for **explicit** regeneration of outputs belonging to that prefix
- `--qwen-width`, `--qwen-height`, `--qwen-steps`, `--shape-steps`,
  `--paint-faces`, `--game-faces`, `--view-resolution`,
  `--texture-size` and `--quality` for defaults across selected parts

Individual card parts may override `generation.reference_width`,
`generation.reference_height`, `generation.shape_steps`,
`generation.target_triangles` (used for the **prepaint** triangle count),
and `generation.view_resolution`. A body reference can therefore be tall
while the head reference remains square. Unset values use CLI defaults.

Re-running `character generate` without `--resume` or `--force` refuses
to touch existing run directories. A batch preflight checks **all selected
parts before launching inference**. Only the Qwen reference and model-stage
processes use CUDA; `--dry-run` only displays the proposed work.

**Important limitations:** this does **not** transfer a mesh from one
part to another, align attachment points, merge neck seams, rig limbs or
guarantee identical character identity across independently sampled Qwen
references. Outputs are separate testable GLBs, not one assembled game
character. Quality approval and assembly are separate future features.

Automated attachment fitting, rigging and full assembly remain future work.

A complete consumer-specific example is at
`examples/space_nova/characters/mara_venn.json`. It shows how to specify
separate full-body and head-focused prompts without introducing game-specific
requirements into the AI3D core.
