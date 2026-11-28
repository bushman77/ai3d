# AI3D

Local, one-command pipeline: **one front image of a character in → one
rigged, textured, game-ready GLB out**, on a 6 GB GPU.

```text
reference → views → cutout → shape → paint-mesh → paint → texture-views → game → rig → report
```

| Stage | Tool | Output |
|---|---|---|
| reference | copy your image (or Qwen text-to-image from `--prompt-file`) | `01_reference.png` |
| views | **Qwen-Image-Edit** draws the same character from left / back / right | `01_view_*.png` |
| cutout | background removal (Hunyuan's rembg) for every view | `02_cutout*.png` |
| shape | **Hunyuan3D-2mv** builds the mesh from all views (2mini if front only) | `03_shape.glb` |
| paint-mesh | Blender clean-up + reduction | `04_paint_mesh.glb` |
| paint | Paint3D texturing | `05_painted.glb` |
| texture-views | Qwen-Image-Edit redraws each view at 1024 px (same content, sharper) | `01_hd_*.png`, `02_hd_cutout_*.png` |
| game | Blender: watertight **quad** mesh, baked colour / normal / roughness, colour **painted straight from the sharp views** | `06_game.glb` |
| rig | Blender: **Mixamo-named skeleton**, automatic weights, test animation, any Mixamo clips in `gestures/` | `07_rigged.glb`, `07_rigged.blend` |
| report | measurements, silhouette match, preview renders | `report.json`, `index.html`, `previews/` |

Everything for a run lands in `outputs/<name>/`. Inputs are never modified.

## One command: `make_character.sh`

Runs the whole procedure and asks you at the two points that need eyes:

```bash
cd ~/ai3d
bash make_character.sh --name mara_v1 \
  --image approved_references/mara_body_front_approved.png --install-as mara_venn
```

1. **Views:** makes left / back / right views and opens them. Press Enter if
   they're right, type the ones to redo (`back`, `left right`, ...; each
   redo is a new seed), `none` to build from the front only, or `q` to stop.
2. **Build:** shape → paint → sharp 1024 px copies of the views → game mesh
   painted from those views (2048 px JPEG, extra texture for the face) → rig with
   `idle` → report. Out of GPU memory in shape? It retries with two views,
   then mv-turbo (if downloaded), then front-only. In Paint3D? It retries
   with the light 6 GB settings. If sharpening the views does, it projects
   the 512 px views as they are.
3. **Review:** prints the numbers and warnings, opens the gallery, asks if
   the poses look right.
4. **Install:** copies the GLB to
   `~/SunRacer/apps/sunracer_web/priv/static/images/game/station/mara_venn.glb`
   and checks the 5 MB target.

It always resumes, so after `q` (or a crash) run the same command again.
`--yes` answers everything for you, `--fresh` starts over,
`--texture-size 1024` for smaller files, `--sunracer PATH` if SunRacer lives
elsewhere. Same as `python3 -m ai3d make ...`.

## Step by step (Mara)

```bash
cd ~/ai3d
git pull

# See the plan and check that every tool/model is found. Nothing runs.
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png --dry-run

# Run everything.
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png

firefox outputs/mara_v1/index.html
blender outputs/mara_v1/07_rigged.blend
```

The run checks every tool and model **before** using the GPU and lists
anything missing, so it can't fail halfway through for a missing file.

### Recommended: check the views before the 3D stages

The side/back views are the step most worth a look. Stop after them,
inspect, then continue:

```bash
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png --stop-after views
xdg-open outputs/mara_v1/01_view_back.png

# Happy? Continue; finished stages are skipped.
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png --resume
```

Bad view? Regenerate just that one with a new random seed (the others are kept):

```bash
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png \
  --stop-after views --resume --redo-view back
```

Or edit/redraw it yourself and pass it in; your own views always win over
generated ones:

```bash
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png \
  --view-back my_fixed_back.png --resume
```

## Gestures

The generated idle only breathes and looks around. For real movement, drop
Mixamo `.fbx` clips into `gestures/` and the rig stage merges each one as an
extra clip named after the file, retargeted by bone name onto the rig this
pipeline builds. SunRacer plays them over the idle at random intervals.

```bash
# Download > FBX Binary, Without Skin, 30 fps, In Place
cp ~/Downloads/Brushing\ Shoulder.fbx gestures/brush_shoulder.fbx
python3 -m ai3d generate --name juno_v1 --prompt-file examples/juno/prompt.txt --resume
```

Rotation is taken and translation is not, so a clip can never walk a station
attendant off its spot. Bones the rig does not have are dropped, which means
Mixamo's finger curves are skipped: this skeleton ends at the hand. With no
clips the stage says so and carries on. See `gestures/README.md`.

## Settings

All settings live in **`config/default.json`** (paths, steps, Paint3D
quality, poly budget, texture size...). Two ways to change them:

```bash
# one-off
python3 -m ai3d generate ... --set shape.steps=50 --set retopo.target_faces=12000

# your own profile, merged over the defaults
cp config/default.json config/mine.json
vim config/mine.json
python3 -m ai3d generate ... --config config/mine.json
```

`config/fast_6gb.json` is the old, quickest Paint3D profile. Every run saves
the exact settings it used in `outputs/<name>/settings.json`. Changing a
setting and using `--resume` reruns only the stages it affects.

Useful switches: `--no-views` (front only), `--no-retopo` (old decimate
behaviour), `--no-rig`, `--seed N`, `--stop-after STAGE`, `--force`,
`--paint-debug`, `--shape-mesh` / `--painted-mesh` to reuse earlier meshes.

## Reading the report

`outputs/<name>/index.html` shows the reference, the views, front / side /
back renders, and the rig in four test poses. `report.json` has the numbers
and a **warnings** list, e.g.:

- **silhouette match** below 0.80: the 3D shape doesn't follow the
  reference outline. Look at the views/cutouts and `03_shape.glb`.
- **pieces > 1 / holes**: the game mesh isn't one closed surface.
- **QuadriFlow failed**: the game mesh fell back to triangles.
- **surface error high**: the low-poly mesh lost detail; raise
  `retopo.target_faces`.
- **automatic weights missed vertices**: check the pose renders.

## The rig

Bones use Mixamo names with the `mixamorig:` prefix (Hips, Spine, Spine1,
Spine2, Neck, Head, Left/Right Shoulder, Arm, ForeArm, Hand, UpLeg, Leg,
Foot, ToeBase). Three.js strips the colon, so tracks named
`mixamorigHips.quaternion` from Mixamo FBX animations line up by name; use
`SkeletonUtils.retargetClip` because the rest pose (A-pose) differs from
Mixamo's T-pose. The character is turned to face −Y (glTF forward) if the
toes point the other way. `07_rigged.blend` is there for hand fixes.

The GLB carries two animations: **`idle`** (8 s seamless loop: arms relaxed
at the sides, angled to clear the hips; breathing; a slow look around) for
use in game, and `ai3d_pose_test` for the report's deformation check. For a
game build with smaller textures: `--set retopo.texture_size=1024`.

Texture quality in the game mesh: the colour comes straight from the sharp
1024 px views. Each surface takes the view that faces it most directly and
can see it (an arm in front doesn't paint the body); Paint3D's colour only
fills what no view sees (top of the head, under the arms). Each view's
outline is fitted to the mesh and side views flip to whichever side
matches; a view that doesn't line up (match < 0.7) is skipped and
reported. Turn off with `texture_views.enabled=false`; use the 512 px views
without redrawing with `texture_views.upscale=false`.

Also: Paint3D's black gaps between
UV pieces are filled before baking (no dark "stitch" seams), the head gets
2.5x the texture density of the body (`retopo.head_boost`), and textures are
stored as JPEG so 2048 px stays near 5 MB (`retopo.image_format`).

## Models you need

Already used before: Qwen-Image-2512 GGUF + Qwen2.5-VL + VAE,
Hunyuan3D-2 checkout and venv, Hunyuan3D-2mini, AiGameKit Paint3D, Blender.
New for multi-view:

```bash
# Qwen-Image-Edit-2509 (side/back views)
hf download QuantStack/Qwen-Image-Edit-2509-GGUF Qwen-Image-Edit-2509-Q3_K_M.gguf \
  --local-dir ~/models/Qwen-Image-Edit-2509
# its vision projector (1.35 GB) lives in QuantStack's older Qwen-Image-Edit repo
hf download QuantStack/Qwen-Image-Edit-GGUF mmproj/Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf \
  --local-dir ~/models/Qwen-Image-Edit-2509

# Hunyuan3D-2mv (multi-view shape). Without this folder it downloads itself.
hf download tencent/Hunyuan3D-2mv --include "hunyuan3d-dit-v2-mv/*" \
  --local-dir ~/ai3d/models/Hunyuan3D-2mv
```

Older `huggingface_hub` installs call the command `huggingface-cli` instead
of `hf`. If your file names differ, set them in your config
(`views.diffusion_model`, `views.llm_vision`). Your `stable-diffusion.cpp`
build must support Qwen-Image-Edit: `sd-cli --help` should list `-r` and
`--llm_vision`. If not, `git pull` and rebuild it.

**6 GB notes.** Hunyuan3D-2mv is 1.1B parameters, the same size as
standard Hunyuan3D-2, which Tencent rates at 6 GB for shape. That's tight
on a 6 GB card, so `shape.low_vram` (on by default) keeps only the diffusion
model on the GPU while it samples. If shape still runs out of memory, try in
this order:

1. Fewer views: `--set 'views.angles=["left","back"]'`
2. The guidance-distilled turbo model, which runs one pass per step instead
   of two (another download):
   `hf download tencent/Hunyuan3D-2mv --include "hunyuan3d-dit-v2-mv-turbo/*" --local-dir ~/ai3d/models/Hunyuan3D-2mv`
   then `--set shape.model=mv-turbo --set shape.steps=10`
3. Front view only: `--set shape.model=mini`

`shape.num_chunks` only matters after sampling, when the mesh is extracted.

Paint3D defaults are higher than before (4 views at 384 px, 2K texture). If
Paint3D runs out of memory, use `--config config/fast_6gb.json`.

## Other commands

```bash
python3 -m ai3d inspect outputs/mara_v1/07_rigged.glb --require-texture
python3 -m ai3d validate-blender some_painted.glb --name check1 --dry-run
```

## Layout

- `pipelines/image_to_3d.py`: the pipeline (standard-library Python)
- `config/`: settings profiles
- `backends/`: scripts run inside the Hunyuan venv (shape, cutout); now tracked here
  instead of living untracked inside the Hunyuan checkout
- `ai3d/blender/`: Blender scripts (prepaint, retopo_bake, rig, quality)
- `ai3d/`: small helpers (config, GLB validation, stage runner, command builders)
- `tests/`: `python3 -m unittest discover -s tests -v`; Blender stage tests run
  when `blender` is on PATH or `AI3D_BLENDER` is set
- `legacy/`: the old parts-based Mara workflow (separate body / head / outfit
  meshes, assembly, cut planes, custom 51-bone rig). Still works; see
  `legacy/README.md`.
- `doctor.sh`, `install.sh`: dependency audit and cautious installer

See `DEPENDENCIES.md` for the full dependency inventory.
