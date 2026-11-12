"""Render every generated character part and create a browser-viewable gallery.

This is intentionally a proof-of-pipeline workflow: it never attempts garment
fitting, editing source meshes, merging, rigging, or automatic quality approval.
Only Python's standard library is needed outside the Blender subprocesses.
"""
import argparse
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
import sys

from ai3d.characters.card import load_card
from ai3d.output import run_directory


VIEWS = ("front", "threequarter", "side")
RENDER_SCRIPT = Path(__file__).with_name("blender_render_component.py")


def prototype_paths(card, prefix, output_dir):
    """Predict paths for every part in card order without filesystem changes."""
    for part in card["parts"]:
        view = part.get("reference_view") or "front"
        name = f"{prefix}_{part['id']}_{view}"
        folder = run_directory(name, output_dir)
        yield {
            "id": part["id"],
            "name": name,
            "folder": folder,
            "glb": folder / "06_game.glb",
            "reference": folder / "01_reference.png",
            "previews": [folder / f"07_preview_{view}.png" for view in VIEWS],
        }


def create_gallery(card, prefix, output_dir, blender="blender",
                   dry_run=False, size=640):
    if size < 64:
        raise RuntimeError("Preview size must be at least 64")
    root = Path(output_dir).expanduser().resolve()
    paths = list(prototype_paths(card, prefix, root))
    gallery_dir = run_directory(f"{prefix}_prototype_gallery", root)
    print(f"\n[ALL-PART 3D GALLERY] {len(paths)} parts", flush=True)
    for entry in paths:
        cmd = [
            blender, "--background", "--factory-startup", "--python-exit-code",
            "1", "--python", str(RENDER_SCRIPT), "--", "--input",
            str(entry["glb"]), "--size", str(size),
        ]
        if dry_run:
            print(f"  [DRY RUN] {entry['id']}: {entry['glb']}", flush=True)
            print("  Blender: " + " ".join(cmd), flush=True)
            continue
        source = entry["glb"]
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(
                f"Cannot render {entry['id']}; no game-stage GLB at {source}. "
                "Re-run --prototype-all-parts to finish its generation."
            )
        existing = all(p.is_file() and p.stat().st_size > 0 and
                       p.stat().st_mtime_ns >= source.stat().st_mtime_ns
                       for p in entry["previews"])
        if existing:
            print(f"  [RESUME] {entry['id']} previews already present", flush=True)
        else:
            print(f"  [RENDER] {entry['id']} from {source}", flush=True)
            subprocess.run(cmd, check=True)
            missing = [str(p) for p in entry["previews"]
                       if not p.is_file() or p.stat().st_size == 0]
            if missing:
                raise RuntimeError(f"Blender did not produce previews: {missing}")

    if dry_run:
        print(f"  [DRY RUN] Gallery would be at {gallery_dir / 'index.html'}")
        return gallery_dir / "index.html"

    gallery_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    report = []
    for entry in paths:
        folder = entry["folder"]
        # Folder names are strictly validated by run_directory.
        def url(name):
            return escape(f"../{folder.name}/{name}", quote=True)
        images = "\n".join(
            f'<figure><a href="{url(path.name)}"><img src="{url(path.name)}" '
            f'alt="{escape(entry["id"])} {escape(view)} view" loading="lazy"></a>'
            f'<figcaption>{escape(view)}</figcaption></figure>'
            for view, path in zip(VIEWS, entry["previews"])
        )
        cards.append(
            f'<section><h2>{escape(entry["id"])}</h2>'
            f'<p><a href="{url("01_reference.png")}">Qwen reference</a> · '
            f'<a href="{url("03_shape.glb")}">Hunyuan shape</a> · '
            f'<a href="{url("05_painted.glb")}">Painted GLB</a> · '
            f'<a href="{url("06_game.glb")}">Optimized GLB</a></p>'
            f'<div class="views">{images}</div></section>'
        )
        report.append({
            "part": entry["id"],
            "run_name": entry["name"],
            "reference": str(entry["reference"]),
            "game_glb": str(entry["glb"]),
            "preview_pngs": [str(p) for p in entry["previews"]],
        })
    title = f"{card['name']} — all component 3D prototypes"
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f'<title>{escape(title)}</title>'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>body{font:16px system-ui;background:#151b24;color:#e7edf6;'
        'padding:24px;max-width:1400px;margin:auto}a{color:#7dd4ff}'
        'section{border:1px solid #39485b;padding:16px;margin:22px 0;'
        'border-radius:12px}.views{display:grid;grid-template-columns:'
        'repeat(auto-fit,minmax(220px,1fr));gap:12px}'
        'figure{margin:0}img{width:100%;border-radius:8px;background:#2c3340}'
        'figcaption{text-align:center;margin:8px}h1,h2{margin-bottom:8px}'
        '</style><body>'
        f'<h1>{escape(title)}</h1>'
        '<p>Each object was generated separately. Unfitted and experimental '
        'components are expected; this gallery is not a finished character.</p>'
        + "\n".join(cards) + "</body></html>"
    )
    index = gallery_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    (gallery_dir / "report.json").write_text(
        json.dumps({"character": card["id"], "prefix": prefix, "parts": report},
                   indent=2) + "\n", encoding="utf-8",
    )
    print(f"\n[DONE] All {len(paths)} 3D prototypes rendered", flush=True)
    print(f"Gallery: {index}", flush=True)
    print(f"Open locally: firefox {index}", flush=True)
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--size", type=int, default=640)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    card = load_card(args.card)
    if not args.dry_run and not (shutil.which(args.blender) or
                                 Path(args.blender).expanduser().is_file()):
        raise RuntimeError(f"Blender executable not found: {args.blender}")
    create_gallery(card, args.prefix, args.output_dir, blender=args.blender,
                   dry_run=args.dry_run, size=args.size)


if __name__ == "__main__":
    main()
