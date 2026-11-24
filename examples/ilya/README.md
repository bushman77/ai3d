# Ilya Quill

Ship Outfitter at the Green Starbase (SunRacer attendant id `outfitting`).
No image exists yet, so the front picture is drawn from `prompt.txt`.

```bash
cd ~/ai3d
bash make_character.sh --name ilya_v1 --prompt-file examples/ilya/prompt.txt --install-as ilya_quill
```

At the first prompt check `01_reference.png` (type `front` to draw it again
with a new seed), then the left / back / right views as for Mara.

Brief: Brad's prompt (drafted with GPT), with its "no ..." items moved into the
negative prompt and a few 3D-friendly negatives added (no coat, loose fabric,
backpack, helmet). Edit `prompt.txt` freely (vim), then redo with
`--redo-view front`.
