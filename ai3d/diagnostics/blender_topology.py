"""Read-only Blender adapter for AI3D's pure-Python topology analyzer.

Usage:
  blender --background hole_in_thigh_exposed.blend --python-exit-code 1 \\
    --python ai3d/diagnostics/blender_topology.py -- \\
    --object Mesh --side negative-x --report topology_report.json

Opening an existing .blend and inspecting its active/edit mesh is safe.
This script NEVER invokes Blender save/export operators and NEVER changes
vertices, edges, faces, materials, collections, visibility, or selections.
Only the explicit JSON report file is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

import bmesh
import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai3d.diagnostics.topology import analyze_mesh


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", default="Mesh", help="Exact Blender mesh-object name")
    parser.add_argument("--side", choices=("negative-x", "positive-x", "both"),
                        default="negative-x", help="Thigh search region in world X")
    parser.add_argument("--report", required=True, type=Path, help="Output JSON file")
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def extract_geometry(obj):
    """Extract current geometry without changing an object or applying modifiers.

    Blender can reopen saved edit-mode scenes still in Edit Mode. In that case
    bpy.data Mesh arrays need not reflect the active edit BMesh, so inspect
    bmesh.from_edit_mesh directly. Neither path writes geometry.
    """
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(obj.data)
        verts = list(bm.verts)
        vert_ids = {vert: i for i, vert in enumerate(verts)}
        points = [tuple(float(c) for c in obj.matrix_world @ vert.co) for vert in verts]
        edges = [(vert_ids[e.verts[0]], vert_ids[e.verts[1]]) for e in bm.edges]
        faces = [tuple(vert_ids[v] for v in face.verts) for face in bm.faces]
    else:
        mesh = obj.data
        points = [tuple(float(c) for c in obj.matrix_world @ v.co) for v in mesh.vertices]
        edges = [tuple(e.vertices) for e in mesh.edges]
        faces = [tuple(poly.vertices) for poly in mesh.polygons]
    return points, edges, faces


def mesh_digest(points, edges, faces):
    """Tie measurements to exact vertex/edge/polygon order; not a semantic ID."""
    digest = hashlib.sha256()
    for point in points:
        digest.update(struct.pack("<3d", *point))
    for a, b in edges:
        digest.update(struct.pack("<2I", a, b))
    for face in faces:
        digest.update(struct.pack("<I", len(face)))
        for v in face:
            digest.update(struct.pack("<I", v))
    return digest.hexdigest()


def main():
    args = arguments()
    source = Path(bpy.data.filepath).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".blend":
        raise RuntimeError("Load an existing .blend scene as Blender's first positional argument")
    out = args.report.expanduser().resolve()
    if out.suffix.lower() != ".json":
        raise RuntimeError("Report destination must be a JSON file")
    if out == source or args.report.is_symlink():
        raise RuntimeError("Refusing to overwrite saved scene or output symlink")
    obj = bpy.data.objects.get(args.object)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"Expected mesh object named {args.object!r} in saved Blender scene")
    points, edges, faces = extract_geometry(obj)
    report = analyze_mesh(points, edges, faces, side=args.side)
    stat = source.stat()
    report["source"] = {
        "scene": str(source),
        "scene_bytes": stat.st_size,
        "scene_mtime_ns": stat.st_mtime_ns,
        "mesh_object": obj.name,
        "mesh_data_name": obj.data.name,
        "parent_object": obj.parent.name if obj.parent else None,
        "mesh_mode_at_load": obj.mode,
        "blender_version": bpy.app.version_string,
        "mesh_sha256": mesh_digest(points, edges, faces),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".topology-", suffix=".tmp", dir=out.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temp, out)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    metrics = report["overview"]
    print("\nAI3D read-only topology report", flush=True)
    print(f"  Scene: {source}", flush=True)
    print(f"  Object: {obj.name} ({obj.mode})", flush=True)
    print(f"  Mesh islands: {metrics['mesh_islands']:,}", flush=True)
    print(f"  Boundary edges: {metrics['boundary_edges']:,}", flush=True)
    print(f"  Closed loops: {metrics['closed_boundary_loops']:,}; "
          f"open chains: {metrics['open_boundary_chains']:,}; "
          f"complex groups: {metrics['complex_boundary_groups']:,}", flush=True)
    roi = report["roi"]
    print(f"  Thigh ROI: {roi['side']}, z=[{roi['z_min']:.3f}, {roi['z_max']:.3f}]", flush=True)
    print(f"  Candidate groups in ROI: {len(report['roi_candidates'])}", flush=True)
    for candidate in report["roi_candidates"][:12]:
        print(f"    {candidate['boundary_id']}: {candidate['kind']}, "
              f"{candidate['boundary_edges']} edges, "
              f"{candidate['vertices_in_roi']} ROI vertices, "
              f"island {candidate['island_id']}", flush=True)
    print(f"  JSON report: {out}", flush=True)
    print("  No mesh edits, repairs, deletions or .blend saves performed.\n", flush=True)


if __name__ == "__main__":
    main()
