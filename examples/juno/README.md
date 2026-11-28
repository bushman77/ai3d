# Juno Rook

Mission Liaison at the Green Starbase (SunRacer attendant id `missions`).
No image exists for her, so the front picture is drawn from `prompt.txt`.

```bash
cd ~/ai3d
bash make_character.sh --name juno_v1 --prompt-file examples/juno/prompt.txt \
  --install-as juno_rook
```

The checkout is at `~/SunRacer`, which is the default, so no `--sunracer`.

At the first prompt check `01_reference.png` (type `front` to draw it again
with a new seed), then the left / back / right views as for Mara.

Brief: drawn from SunRacer's `docs/story/CHARACTERS.md` — discreet, patient
and evidence-led, a liaison who waits for evidence rather than a field
officer, so the pose and face are composed rather than imposing. Her
slate-blue uniform follows the procedural figure she replaces (attendant
colour `0x8ca8dd`), which keeps the swap from being jarring, and is
deliberately distinct from Mara's forest-green and Ilya's mustard
engineering jumpsuits: a closed uniform tunic and trousers rather than a
jumpsuit. Her hands stay empty — a held datapad would read as geometry
fused to the fingers in the shape stage and fight the rig — and the bun
keeps hair off the silhouette for retopo. Edit `prompt.txt` freely (vim),
then redo with `--redo-view front`.
