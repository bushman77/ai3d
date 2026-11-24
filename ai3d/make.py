"""ai3d make: the whole character procedure in one guided command.

    python3 -m ai3d make --name mara_v1 \
        --image approved_references/mara_body_front_approved.png \
        --install-as mara_venn

What it does, in order (everything we learned building Mara):

1. Generates the left / back / right views and opens them. You approve
   them, or name the ones to redo (each redo uses a new random seed).
   What to look for is printed next to the prompt.
2. Builds the rest: shape -> paint -> sharp 1024 px copies of the views ->
   game mesh painted from those views -> rig -> report, with game textures at
   2048 px (JPEG) by default.
3. If the shape stage runs out of GPU memory it retries, in order: fewer
   views (left + back), mv-turbo (only if downloaded), front-only mini.
   If Paint3D runs out of memory it retries with the light 6 GB settings; if
   the view sharpening does, it projects the 512 px views as they are.
4. Prints the report numbers and warnings and opens the gallery, then asks
   whether the poses look right.
5. Copies the rigged GLB into SunRacer's station folder (--install-as NAME)
   and checks it against the 5 MB target.

Every run resumes: finished stages are skipped, so you can stop at any
prompt (q) and run the same command again later. --yes skips the questions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from ai3d.config import load_profile, repo_path
from ai3d.output import DEFAULT_OUTPUT_ROOT

ANGLES = ("left", "back", "right")
SUNRACER = Path("~/SunRacer")
STATION_DIR = Path("apps/sunracer_web/priv/static/images/game/station")
SIZE_TARGET_MB = 5.0

VIEW_CHECKS = """\
With --prompt-file, check 01_reference.png first: full body head to feet,
facing you, arms out, plain background, looks like the character you want
(type 'front' to draw it again).
Check each view:
  - the SAME character as the front image (outfit, colours, hair, build)
  - the WHOLE body turned, not just the head (back view: heels, no face)
  - left and right face opposite ways; full body head to feet; no extras"""

POSE_CHECKS = """\
Check the gallery:
  - front / side / back look like the reference
  - idle frames: arms relaxed at the sides, hands clear of the hips
  - pose 020 arms up and 040 arms down: hips and thighs keep their shape
  - pose 060 / 080 knee bends: no tearing or pinching"""

PAINT_LIGHT = ["paint.quality=fast", "paint.max_views=2", "paint.view_resolution=256",
               "paint.render_size=512", "paint.texture_size=1024"]


def arguments(argv):
    p = argparse.ArgumentParser(
        prog="ai3d make", description=__doc__.split("\n\n")[0],
        epilog="Everything else (steps, budgets, paths) lives in config/default.json.")
    p.add_argument("--name", required=True, help="Run name; files go to outputs/<name>/")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", type=Path, help="Front reference image")
    src.add_argument("--prompt-file", type=Path, help="Text prompt for Qwen text-to-image")
    p.add_argument("--install-as", metavar="NAME",
                   help="Copy the result to SunRacer as station/NAME.glb (e.g. mara_venn)")
    p.add_argument("--sunracer", type=Path, default=SUNRACER,
                   help="SunRacer checkout (default: ~/SunRacer)")
    p.add_argument("--texture-size", type=int, default=2048,
                   help="Game texture size (default 2048; JPEG keeps it near the 5 MB target)")
    p.add_argument("--config", type=Path, help="Profile merged over config/default.json")
    p.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    p.add_argument("--fresh", action="store_true",
                   help="Delete outputs/<name> first and start over")
    p.add_argument("--yes", action="store_true",
                   help="No questions: accept views and poses, install if --install-as")
    p.add_argument("--viewer", default="xdg-open", help="Program that opens images/HTML")
    return p.parse_args(argv)


class Maker:
    def __init__(self, a, *, pipeline=None, ask=input, opener=None, say=print):
        if pipeline is None:
            from pipelines.image_to_3d import main as pipeline
        self.a = a
        self.pipeline = pipeline
        self.ask = ask
        self.say = say
        self.opener = opener or self._open
        self.home = a.output_dir.expanduser() / a.name
        self.extra = [f"retopo.texture_size={a.texture_size}"]
        self.cfg = load_profile(a.config, list(a.set))

    # ---------------------------------------------------------------- helpers
    def _open(self, path: Path) -> None:
        if shutil.which(self.a.viewer):
            subprocess.Popen([self.a.viewer, str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            self.say(f"  (open it yourself: {path})")

    def base_args(self) -> list[str]:
        args = ["--name", self.a.name, "--output-dir", str(self.a.output_dir), "--resume"]
        args += ["--image", str(self.a.image)] if self.a.image else \
            ["--prompt-file", str(self.a.prompt_file)]
        if self.a.config:
            args += ["--config", str(self.a.config)]
        for item in [*self.a.set, *self.extra]:
            args += ["--set", item]
        return args

    def run(self, *more: str) -> None:
        self.pipeline([*self.base_args(), *more])

    def question(self, prompt: str, default: str = "") -> str:
        if self.a.yes:
            return default
        try:
            return self.ask(prompt).strip().lower() or default
        except EOFError:
            return "q"

    def failed_stage_log(self, error: Exception) -> tuple[str, str]:
        text = str(error)
        stage = text.split(" failed", 1)[0] if " failed" in text else ""
        log = ""
        if "Full log:" in text:
            path = Path(text.split("Full log:", 1)[1].strip())
            if path.is_file():
                log = path.read_text(errors="replace")[-20000:]
        return stage, log

    @staticmethod
    def out_of_memory(log: str) -> bool:
        markers = ("OutOfMemoryError", "CUDA out of memory",           # PyTorch
                   "cannot make enough memory available",             # stable-diffusion.cpp
                   "failed during weight preparation", "out of memory")
        return any(m in log for m in markers)

    def views_enabled(self) -> bool:
        return bool(self.cfg["views"]["enabled"]) and "views.enabled=false" not in self.extra

    # ---------------------------------------------------------------- steps
    def step_views(self) -> bool:
        if not self.views_enabled():
            return True
        self.say("\n=== 1. Side and back views ===")
        self.run("--stop-after", "views")
        while True:
            views = [self.home / f"01_view_{v}.png" for v in self.cfg["views"]["angles"]]
            views = [v for v in views if v.is_file()]
            if self.a.prompt_file and (self.home / "01_reference.png").is_file():
                views.insert(0, self.home / "01_reference.png")
            for view in views:
                self.say(f"  {view}")
                self.opener(view)
            self.say(VIEW_CHECKS)
            redo_names = "front/left/back/right" if self.a.prompt_file else "left/back/right"
            answer = self.question(
                f"Views OK? [Enter]=yes, or the ones to redo ({redo_names}, e.g. 'back'), "
                "'none'=build without views, q=stop: ", default="")
            if answer in ("", "y", "yes"):
                return True
            if answer == "q":
                self.say("Stopped. Run the same command again to continue.")
                return False
            if answer == "none":
                self.extra.append("views.enabled=false")
                self.say("Building from the front view only.")
                return True
            allowed = (*ANGLES, "l", "b", "r") + (("front", "f") if self.a.prompt_file else ())
            redo = [w for w in answer.replace(",", " ").split() if w in allowed]
            redo = [{"l": "left", "b": "back", "r": "right", "f": "front"}.get(w, w) for w in redo]
            if "front" in redo:
                self.say("New front image: the side and back views are redrawn from it too.")
            if not redo:
                self.say("Didn't understand; type e.g. 'back' or 'left right'.")
                continue
            args = ["--stop-after", "views"]
            for angle in dict.fromkeys(redo):
                args += ["--redo-view", angle]
            self.run(*args)

    def fallbacks(self, stage: str) -> list[tuple[str, list[str]]]:
        if stage == "shape":
            steps = [("two side views (left + back)", ['views.angles=["left","back"]'])]
            turbo = repo_path(self.cfg["paths"]["hunyuan_models"]) / \
                "Hunyuan3D-2mv" / "hunyuan3d-dit-v2-mv-turbo"
            if turbo.is_dir():
                steps.append(("mv-turbo (one pass per step)",
                              ["shape.model=mv-turbo", "shape.steps=10"]))
            steps.append(("front view only (Hunyuan3D-2mini)", ["shape.model=mini"]))
            return steps
        if stage == "paint":
            return [("light Paint3D settings (6 GB profile)", PAINT_LIGHT)]
        if stage.startswith("texture-views"):
            return [("sharpening at 768 px instead of 1024", ["texture_views.size=768"]),
                    ("the 512 px views as they are (no sharpening)",
                     ["texture_views.upscale=false"])]
        return []

    def step_build(self) -> bool:
        self.say("\n=== 2. Shape, paint, game mesh, rig, report ===")
        tried: dict[str, int] = {}
        while True:
            try:
                self.run()
                return True
            except RuntimeError as error:
                stage, log = self.failed_stage_log(error)
                options = self.fallbacks(stage)
                if stage.startswith("texture-views"):
                    stage = "texture-views"
                attempt = tried.get(stage, 0)
                if not (self.out_of_memory(log) and attempt < len(options)):
                    self.say(f"\nERROR: {error}")
                    if self.out_of_memory(log):
                        self.say("Out of GPU memory and no fallbacks left. Close other GPU "
                                 "programs (browser, game) and run the same command again.")
                    return False
                label, sets = options[attempt]
                tried[stage] = attempt + 1
                self.say(f"\n{stage} ran out of GPU memory; retrying with {label}.")
                self.extra += sets

    def step_review(self) -> bool:
        self.say("\n=== 3. Report ===")
        report_path = self.home / "report.json"
        if not report_path.is_file():
            self.say(f"No report at {report_path}")
            return False
        report = json.loads(report_path.read_text())
        q = report["stats"].get("quality_game", {})
        r = report["stats"].get("rig", {})
        mesh = q.get("mesh", {})
        self.say(f"  silhouette match {q.get('silhouette_iou')}   triangles {mesh.get('triangles')}"
                 f"   pieces {mesh.get('pieces')}   holes {mesh.get('boundary_edges')}")
        if r:
            self.say(f"  bones {r.get('bones')}   weights {r.get('weight_method')}"
                     f"   shoulders at {r.get('shoulder_height_fraction')}"
                     f"   arm leak {r.get('arm_leak')}   clips {r.get('actions')}")
        for warning in report["warnings"]:
            self.say(f"  WARNING: {warning}")
        if not report["warnings"]:
            self.say("  No warnings.")
        if self.extra[1:]:
            self.say("  Settings used besides the defaults: " + " ".join(self.extra))
        gallery = self.home / "index.html"
        self.say(f"  Gallery: {gallery}")
        self.opener(gallery)
        self.say(POSE_CHECKS)
        answer = self.question("Do the model and poses look right? [y/n]: ", default="y")
        if answer not in ("y", "yes"):
            self.say("Not installing. Tell Claude what looks wrong (send the gallery), or "
                     "fix 07_rigged.blend by hand in Blender.")
            return False
        return True

    def step_install(self) -> None:
        name = self.a.install_as
        if not name:
            if self.a.yes:
                return
            name = self.question("Copy into SunRacer? station asset name (e.g. mara_venn), "
                                 "Enter=skip: ", default="")
            if not name or name == "q":
                return
        name = name.removesuffix(".glb")
        source = self.home / "07_rigged.glb"
        if not source.is_file():
            source = self.home / "06_game.glb"
        station = self.a.sunracer.expanduser() / STATION_DIR
        if not station.is_dir():
            self.say(f"SunRacer station folder not found: {station}  (use --sunracer PATH)")
            return
        target = station / f"{name}.glb"
        shutil.copy2(source, target)
        size = target.stat().st_size / 1e6
        self.say(f"\n=== 4. Installed ===\n  {target}  ({size:.1f} MB)")
        if size > SIZE_TARGET_MB:
            self.say(f"  Over the {SIZE_TARGET_MB:.0f} MB target; try --texture-size 1024.")
        self.say("  Reload the game and walk to the character. To ship it:\n"
                 f"    cd {self.a.sunracer}\n    git add {STATION_DIR / target.name}\n"
                 f"    git commit -m \"Add {name} model\"")

    def go(self) -> int:
        if self.a.fresh and self.home.exists():
            answer = self.question(f"Delete {self.home} and start over? [y/N]: ", default="y")
            if answer in ("y", "yes"):
                shutil.rmtree(self.home)
        if not self.step_views():
            return 1
        if not self.step_build():
            return 1
        if not self.step_review():
            return 1
        self.step_install()
        return 0


def main(argv: list[str] | None = None) -> int:
    a = arguments(argv)
    if a.image and not a.image.expanduser().is_file():
        print(f"Image not found: {a.image}")
        return 1
    if a.image:
        a.image = a.image.expanduser().resolve()
    return Maker(a).go()


if __name__ == "__main__":
    raise SystemExit(main())
