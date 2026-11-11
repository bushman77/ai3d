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
