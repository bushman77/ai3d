# Read-only topology diagnostics

AI3D records mesh islands and open boundary geometry in a saved Blender scene.
This milestone does NOT remove, replace, classify or repair any geometry.
Open boundary edges do not necessarily indicate holes.

## Run headlessly from the project root

```bash
cd ~/ai3d
./build_character.sh --diagnose
```

The default scene is outputs/mara_complete_v1_assembly/hole_in_thigh_exposed.blend.
The report is outputs/mara_complete_v1_assembly/topology_hole_in_thigh_exposed.json.

To override the source, inspected object or thigh window:

```bash
./build_character.sh --diagnose --diagnose-blend /path/to/scene.blend \
  --diagnose-object Mesh --diagnose-side negative-x \
  --diagnose-report /path/to/topology.json
```

negative-x corresponds approximately to screen-left in Front Orthographic view.
Choose positive-x or both for other regions. The default thigh search window
covers 30%-68% of the mesh object's world-space height and one half of X.
This window ranks candidate boundaries; it does not identify anatomy.

## Report content

- Connected mesh islands, vertex/face/triangle counts and world-space bounds.
- True mesh-boundary edges (one adjacent face), wire edges (zero faces) and
  edges shared by more than two faces.
- Connected boundary groups labelled closed_loop, open_chain, or branched_or_complex.
- A shortlist of boundary groups intersecting the thigh-region search window.
- Source file path, size, modification time, geometry SHA256 and vertex indices.

Some boundaries are mesh seams, separate surfaces or extraction artifacts.
Never delete or fill topology based solely on this report.
All vertex and edge indices refer only to the exact saved mesh topology.

Saved edit-mode scenes are supported: the adapter reads Blender's edit BMesh.
The analyzer writes ONLY the selected JSON report. It never saves .blend files,
alters imported materials, invokes model inference, or exports GLBs.

## Test without Blender

```bash
python3 -m unittest discover -s tests -p test_topology_analysis.py -v
```

The Blender adapter still requires a local runtime test on a real .blend file.

## Mara-specific thigh prototype (non-destructive)

The default `--thigh-prototype` now uses a **mesh-guided open side panel**,
not the original fixed-radius cylinder. It samples the surviving front and
rear leg-surface islands in the experimental Mara mesh, excluding short
equipment fragments. It only spans the measured thigh height where the
original geometry supplies sufficient samples. Its outward X extent is
limited to 0.004 units beyond the observed contour. Missing front/rear
support aborts generation rather than guessing a replacement.

```bash
cd ~/ai3d
git pull --ff-only
./build_character.sh --thigh-prototype
```

Input: `outputs/mara_complete_v1_assembly/hole_in_thigh_exposed.blend`.
New output: `outputs/mara_complete_v1_assembly/thigh_guided_prototype.blend`.
**Neither the input nor the previous fixed-station preview is overwritten.**

Open the result in Blender and inspect the cyan
`AI3D_Thigh_GuidedPatch_TEST` object under
`AI3D_THIGH_REPAIR_PROTOTYPE`, from the front, side and three-quarter
views. The panel has OPEN front/rear and top/bottom boundaries. It is not
welded to the original clothing and may still show seams, interference
with remaining holster pieces or exposed texture transitions. It is
**NOT APPROVED for static/game export**. The scene saves metadata on the
test object describing sampled contours and source-island counts.

The older closed-cylinder experiment is still available explicitly:

```bash
./build_character.sh --thigh-prototype --thigh-method stations
```

Its output remains `thigh_underlay_prototype.blend`. Existing prototype
outputs are never overwritten implicitly. The `--force` option explicitly
permits rebuilding an output; `--thigh-inset 0.006` nudges the guided
panel inward along +X (or shrinks the old station-based shell's radii).
The saved .blend source is always preserved.

The Blender adapter also checks that this exact experimental body still
has 20,633 vertices and 33,129 polygons, with an identity world transform,
before fitting. These guards reduce accidental fitting to another model,
but do not establish watertightness, texture quality or anatomical accuracy.

Unit tests check the contour generation, exclusion of short equipment
islands, refusal to guess with missing surface support, and inset behavior.
The shell remains a prototype until a Blender visual review and a separate
topology/texture/occlusion validation pass.
