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

Only the **reference-image stage** is implemented here. Automated per-part
geometry, attachment fitting, rigging and full assembly remain future work.

A complete consumer-specific example is at
`examples/space_nova/characters/mara_venn.json`. It shows how to specify
separate full-body and head-focused prompts without introducing game-specific
requirements into the AI3D core.
