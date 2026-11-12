"""Build a local HTML contact sheet of separately generated 3D prototypes.

Standard library only; never changes the source GLBs or their render images.
"""
import argparse
import subprocess
import sys
from html import escape
import json
from pathlib import Path
from urllib.parse import quote

VIEWS = ("front", "threequarter", "side")  # original 3-view API
GALLERY_VIEWS = ("front", "side", "back", "threequarter")


def gallery(card, prefix, output_dir, selected):
    allowed = {part["id"]: part for part in card["parts"]}
    if not selected:
        selected = list(allowed)
    for part in selected:
        if part not in allowed:
            raise ValueError(f"Unknown character component: {part}")

    tiles = []
    for part_id in selected:
        part = allowed[part_id]
        view = part.get("reference_view") or "front"
        name = f"{prefix}_{part_id}_{view}"
        source_dir = output_dir / name
        model = source_dir / "05_painted.glb"
        model_state = "Generated 3D" if model.is_file() and model.stat().st_size else "No painted 3D mesh yet"
        tiles.append(f"<section class='component'><header><h2>{escape(part['label'])}</h2>"
                     f"<span>{escape(part_id)} · {escape(model_state)}</span></header>"
                     "<div class='views'>")
        for side in GALLERY_VIEWS:
            picture = source_dir / f"preview_{side}.png"
            if picture.is_file() and picture.stat().st_size:
                rel = quote(f"../{name}/preview_{side}.png", safe="/")
                tiles.append(f"<figure><a href='{rel}'><img loading='lazy' src='{rel}' "
                             f"alt='{escape(part_id)} from {escape(side)}'></a>"
                             f"<figcaption>{escape(side)}</figcaption></figure>")
            else:
                tiles.append(f"<figure class='missing'>No {escape(side)} render</figure>")
        tiles.append("</div>")
        if model.is_file() and model.stat().st_size:
            rel = quote(f"../{name}/05_painted.glb", safe="/")
            tiles.append(f"<p><a href='{rel}'>Open standalone textured GLB</a></p>")
        tiles.append("</section>")

    title = escape(card["name"]) + " · Standalone 3D prototypes"
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>{title}</title>
<style>
:root{{color-scheme:dark}}body{{background:#10151c;color:#eef2f6;font:16px/1.5 system-ui,sans-serif;
margin:0 auto;max-width:1400px;padding:2rem}}h1{{font-size:2rem}}h2{{font-size:1.2rem;margin:0}}
p,span,figcaption{{color:#abb8c9}}.component{{border:1px solid #344253;border-radius:14px;
padding:18px;margin:20px 0;background:#19212c}}.component header{{display:flex;flex-wrap:wrap;
justify-content:space-between;gap:10px}}.views{{display:grid;grid-template-columns:repeat(auto-fit,
minmax(190px,1fr));gap:12px;margin-top:16px}}figure{{margin:0}}figure img{{width:100%;
aspect-ratio:6/7;object-fit:contain;background:#252d37;border-radius:8px}}
figcaption{{text-align:center}}a{{color:#8bc9ff}}.missing{{display:flex;align-items:center;
justify-content:center;min-height:140px;color:#b4a0a0}}
</style></head><body><h1>{title}</h1>
<p>Independent GLB meshes generated per part. No fitting, rigging, or assembly is implied.
Source files remain in their own run directories.</p>
{''.join(tiles)}
</body></html>
"""


def prototype_paths(card, prefix, output_dir):
    """Existing game-stage preview contract; kept for API compatibility."""
    root = Path(output_dir)
    for part in card["parts"]:
        part_id = part["id"]
        view = part.get("reference_view") or "front"
        folder = root / f"{prefix}_{part_id}_{view}"
        yield {
            "id": part_id,
            "folder": folder,
            "glb": folder / "06_game.glb",
            "previews": tuple(folder / f"07_preview_{side}.png" for side in VIEWS),
        }


def create_gallery(card, prefix, output_dir, *, blender="blender", dry_run=False):
    """Historical three-view game-stage gallery; no AI inference.

    This separate API remains usable for existing integrations and tests.
    The standalone seven-part coordinator uses the painted-stage four-view
    `gallery()` function instead.
    """
    output_dir = Path(output_dir)
    index = output_dir / f"{prefix}_prototypes" / "index.html"
    parts = list(prototype_paths(card, prefix, output_dir))
    for part in parts:
        print(f"{part['id']}: {part['glb']}")
    if dry_run:
        return index
    missing = [p["glb"] for p in parts if not p["glb"].is_file() or
               p["glb"].stat().st_size == 0]
    if missing:
        raise RuntimeError("Missing or empty game-stage GLB; no game-stage GLB for: " +
                           ", ".join(str(path) for path in missing))
    script = Path(__file__).with_name("blender_render_component.py")
    for part in parts:
        if all(path.is_file() and path.stat().st_size > 0 for path in part["previews"]):
            continue
        command = [
            blender, "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(script), "--",
            "--input", str(part["glb"]), "--output-dir", str(part["folder"]),
            "--part", part["id"], "--filename-prefix", "07_preview",
        ]
        subprocess.run(command, check=True)
        if not all(path.is_file() and path.stat().st_size > 0 for path in part["previews"]):
            raise RuntimeError("Blender did not produce expected 07_preview PNG files")

    tiles = []
    for part in parts:
        tiles.append("<section><h2>" + escape(part["id"]) + "</h2>")
        for side, path in zip(VIEWS, part["previews"]):
            rel = quote(f"../{part['folder'].name}/{path.name}", safe="/")
            tiles.append(f"<img src='{rel}' alt='{escape(part['id'])} {side}'>")
        tiles.append("</section>")
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body>" +
                     "".join(tiles) + "</body></html>", encoding="utf-8")
    report = {"parts": [
        {"id": part["id"], "glb": str(part["glb"]),
         "previews": [str(path) for path in part["previews"]]}
        for part in parts
    ]}
    (index.parent / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                               encoding="utf-8")
    return index

def main():
    parser = argparse.ArgumentParser(description="Produce standalone 3D render gallery")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--part", action="append", default=[])
    args = parser.parse_args()
    if not args.prefix or not all(c.isalnum() or c in "-_" for c in args.prefix):
        parser.error("invalid --prefix")
    with args.card.open(encoding="utf-8") as source:
        card = json.load(source)
    root = args.output_dir.expanduser().resolve()
    folder = root / f"{args.prefix}_prototypes"
    if folder.is_symlink():
        raise RuntimeError("Refusing symlink gallery directory")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "index.html"
    if target.is_symlink():
        raise RuntimeError("Refusing symlink gallery index")
    target.write_text(gallery(card, args.prefix, root, args.part), encoding="utf-8")
    print("Standalone 3D prototype gallery:", target)


if __name__ == "__main__":
    main()
