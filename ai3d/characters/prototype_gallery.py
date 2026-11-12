"""Build a local HTML contact sheet of separately generated 3D prototypes.

Standard library only; never changes the source GLBs or their render images.
"""
import argparse
from html import escape
import json
from pathlib import Path
from urllib.parse import quote

VIEWS = ("front", "side", "back", "threequarter")


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
        for side in VIEWS:
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
