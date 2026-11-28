# Gesture clips

Drop Mixamo `.fbx` animations here and the rig stage merges each one into the
character as an extra clip, named after the file. `brush_shoulder.fbx` becomes
a clip called `brush_shoulder`. SunRacer then plays them over the idle at
random intervals.

Nothing here is required: with no files, or no folder, the rig stage says so
and carries on with the idle alone.

## Getting them

At [mixamo.com](https://www.mixamo.com) (free Adobe account), pick an
animation and use **Download → FBX Binary (.fbx), Without Skin, 30 fps**, with
**In Place** ticked where it is offered. Without Skin keeps the file to the
motion alone. The skeleton this pipeline builds uses Mixamo's own bone names,
so the clips land without any retargeting work.

Useful ones for a station attendant: `Brushing Shoulder`, `Looking Around`,
`Weight Shift`, `Checking Watch`, a standing `Idle` variant, `Head Nod Yes`.

Rename each file to the clip name you want before dropping it in.

## What the merge does and does not do

- **Rotation only.** Mixamo authors at its own proportions, and copied
  translation would slide an attendant off the spot the server gave it or sink
  it through the floor.
- **Retargets, not copies.** Mixamo's rest pose is not this rig's, so each
  bone's rotation is read as its difference from its own rest, carried through
  world space, and re-expressed in the target bone's space.
- **Drops bones this skeleton lacks.** The rig ends at the hand, so Mixamo's
  finger curves are skipped. Hand-detail gestures will not read; whole-body
  ones will.

## Licensing

The `.fbx` files are deliberately not committed (see `.gitignore`). Mixamo
content is free to use in your projects under Adobe's terms, but
redistributing the source animation files in a public repository is a
different question from using them. Keep them local unless you have checked
that.
