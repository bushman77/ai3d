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

## Mara-specific thigh underlay prototype (non-destructive)

This experimental construction uses fitted stations from the uploaded
Mara preview and exposed-thigh scenes. The shell is watertight **on its own**
but does not weld to clothing, has no UV texture, and does not erase remaining
holster surfaces. It is not yet suitable for game export.

```bash
cd ~/ai3d
git pull --ff-only
./build_character.sh --thigh-prototype
```

That command loads only
`outputs/mara_complete_v1_assembly/hole_in_thigh_exposed.blend`
and saves a separate scene:
`outputs/mara_complete_v1_assembly/thigh_underlay_prototype.blend`.

Open the new file in Blender. The diagnostic cyan object appears in
`AI3D_THIGH_REPAIR_PROTOTYPE` as `AI3D_Thigh_Underlay_TEST`. Inspect
front, side and 3/4 views with the material/color visible. Adjusting
the underlay is experimental: use `--thigh-inset 0.006` to shrink its
cross-section slightly, plus `--force` to replace an existing prototype.

The script explicitly checks the experimental Mara body vertex/face counts
(20,633/33,129) and identity transform before fitting; it rejects other
source meshes instead of applying inappropriate proportions.

Known limitation: the uploaded scene still has protruding holster-like
geometry; a shell alone cannot remove that. Later milestones must verify
remaining islands, fit surface curvature, handle seam materials/UVs,
and test a separate game export before approving the result.
