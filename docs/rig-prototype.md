# Skeleton-only rig prototype for Mara Venn

This is the **first rigging milestone**, after the assembled character has
been reviewed. It adds a visible Blender armature, but **does not yet skin,
weight-paint, animate, merge, or re-export a game-ready character**.

## Generate the skeleton scene

From the AI3D repository (no neural models or GPU inference are used):

```bash
cd ~/ai3d
./build_character.sh --rig-prototype --prefix mara_clean_v2 --dry-run
./build_character.sh --rig-prototype --prefix mara_clean_v2
```

The existing assembled scene is read from:

```text
outputs/mara_clean_v2_workable_character/preview.blend
```

It must already exist, alongside the matching `assembly.json` from
`--assemble-workable`. The new files are:

```text
outputs/mara_clean_v2_rig_prototype/
  rig_prototype.blend     # Separate Blender scene, original meshes and new armature
  skeleton.json          # Bone hierarchy and proposed world-space landmarks
```

Open for manual review:

```bash
blender outputs/mara_clean_v2_rig_prototype/rig_prototype.blend
```

In Blender, select `AI3D_Humanoid_Prototype` and enter **Edit Mode**.
Adjust the proposed hip, chest, shoulder, elbow, wrist, knee, ankle, neck and
head joints against the model in front and side views. The armature remains
separate from all mesh objects: posing a bone **does not yet deform Mara**.

The starting skeleton includes 20 bones: root, pelvis, spine, chest, neck,
head, and paired clavicles, upper arms, forearms, hands, thighs, shins and
feet. Positions are intentionally rough, derived from the assembled body's
ground/center and head height; they are not AI-detected anatomical joints.

## Options

An alternative **existing** assembly can be chosen without affecting the
default:

```bash
./build_character.sh --rig-prototype --prefix mara_clean_v2 \
  --assembly mara_clean_v2_another_workable_scene
```

An existing rig prototype is never silently overwritten. After manually
saving adjustments to the generated rig file, **do not rerun with `--force`**:
that deliberately recreates the prototype from the original assembly
and discards rig-specific edits.

If the source assembly is missing, run the existing `--assemble-workable`
step first. Do not regenerate any of the 3D parts unless a reviewed
component requires repair.

## Planned later milestones

1. Check skeleton size and joint placement visually, edit and approve.
2. Bind body/garments/hands to the armature with weights, and attach equipment
   to an appropriate bone, without throwing away the master assets.
3. Bend elbows and knees and correct skin weights.
4. Export a **separately validated** skinned glTF/GLB, then test animation
   in Three.js before introducing optimized game LODs.

**Important:** `ai3d/optimization/blender_finalize.py` is currently a
static-mesh optimizer and explicitly exports without skinning/animation.
Do not use it to process a future rigged Mara until that pipeline is extended.

## Saved-scene verification

The rig builder now asks Blender to **open the existing assembly .blend
before running any Python**, rather than loading it from inside a running
script. It then opens the newly saved rig file in a **second Blender process**
and checks that the expected armature, bone names, body hierarchy, and
character meshes are all present. Invalid output is rejected and not
published as a successful rig.

If an earlier rig output opens as the factory Cube/Camera/Light scene, preserve
it for diagnosis instead of saving over it. Check that the original
`outputs/PREFIX_workable_character/preview.blend` contains the assembled
character. Rename the old `PREFIX_rig_prototype` output directory to a
backup, then regenerate the rig from the verified assembly.
