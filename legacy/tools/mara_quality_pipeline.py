#!/usr/bin/env python3
"""Mara quality-first pipeline: approved master -> conditioned details -> reviewed 3D.

This is an ADDITIVE entry point. It does not remove or bypass the safety guards
in legacy/characters/{reference,batch}.py. No output stage receives approval
without an explicit human command and a matching SHA-256 digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

MASTER_SHA = "144d06916502ecb524e4113f8bc11b9ab80bfa6714290773a7046d23bd4e2791"
PARTS = (
    "torso_pelvis", "head", "left_arm", "right_arm", "left_hand", "right_hand",
    "left_leg", "right_leg", "left_foot", "right_foot",
)
STAGES = ("reference", "shape", "paint", "game")
PREVIOUS = {"shape": "reference", "paint": "shape", "game": "paint"}
SOURCE_CROPS = "outputs/mara_reference_refine_v1"
DEFAULT_CARD = "legacy/examples/space_nova/characters/mara_venn_anatomical.json"
DEFAULT_MASTER = "approved_references/mara_body_front_approved.png"

class PipelineError(RuntimeError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".quality-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run_command(cmd: list[str], *, dry: bool = False, cwd: Path | None = None, env=None) -> None:
    import shlex
    print("$ " + shlex.join([str(s) for s in cmd]), flush=True)
    if not dry:
        subprocess.run([str(s) for s in cmd], cwd=cwd, check=True, env=env)


def is_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def resolve_within(base: Path, relative: str) -> Path:
    dest = (base / relative).resolve()
    if not dest.is_relative_to(base.resolve()):
        raise PipelineError(f"Output escaped root: {relative}")
    return dest


class QualityWorkflow:
    def __init__(self, args):
        self.args = args
        self.root = args.root.resolve()
        self.master = resolve_within(self.root, args.master)
        self.card_path = resolve_within(self.root, args.card)
        self.out = resolve_within(self.root, f"outputs/{args.run}")
        self.state_path = self.out / "quality_state.json"
        self.crops = self.root / SOURCE_CROPS
        if not is_file(self.master):
            raise PipelineError(f"Approved master missing or unsafe: {self.master}")
        actual = digest(self.master)
        if actual != MASTER_SHA:
            raise PipelineError(f"Approved master SHA mismatch; expected {MASTER_SHA}, found {actual}. Refusing all work.")
        if not is_file(self.card_path):
            raise PipelineError(f"Anatomical card missing: {self.card_path}; run legacy/tools/prepare_mara_anatomy.py to create it")
        self.card = json.loads(self.card_path.read_text(encoding="utf-8"))
        parts = {p["id"]: p for p in self.card["parts"]}
        if self.card.get("id") != "mara_venn" or any(pid not in parts for pid in PARTS):
            raise PipelineError("Anatomical card lacks the exact required Mara components")
        if not all(parts[pid].get("generation", {}).get("approved_master_required") is True for pid in PARTS):
            raise PipelineError("Anatomical card approval lock missing; refusing this workflow")
        self.parts = parts
        if self.state_path.exists():
            if self.state_path.is_symlink():
                raise PipelineError("Refusing symlinked quality state")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if (self.state.get("master_sha256") != MASTER_SHA or
                self.state.get("card_sha256") != digest(self.card_path)):
                raise PipelineError("Master/card changed since this run; use a NEW --run name")
        else:
            self.state = {
                "version": 1,
                "master_sha256": MASTER_SHA,
                "card_sha256": digest(self.card_path),
                "run": args.run,
                "parts": {},
            }

    def selected(self):
        if self.args.all_parts:
            return list(PARTS)
        if not self.args.part:
            if self.args.stage == "plan":
                return list(PARTS)
            raise PipelineError("Choose --part head (etc.) or --all-parts")
        for part in self.args.part:
            if part not in PARTS:
                raise PipelineError(f"Unknown anatomical component {part!r}")
        return list(dict.fromkeys(self.args.part))

    def write(self):
        if not self.args.dry_run:
            atomic_json(self.state_path, self.state)

    def record(self, part: str, stage: str):
        return self.state["parts"].setdefault(part, {}).setdefault(stage, {})

    def paths(self, part: str):
        d = self.out / part
        return {
            "reference": d / "reference_edit.png",
            "shape": d / "03_shape.glb",
            "paint": d / "05_painted.glb",
            "game": d / "06_game.glb",
        }

    def check_approval(self, part: str, stage: str):
        record = self.state["parts"].get(part, {}).get(stage, {})
        path = self.paths(part)[stage]
        if not is_file(path) or not record.get("approved_sha256"):
            raise PipelineError(f"{part}: {stage} is not approved. Inspect it, then use --stage approve --approve {stage} --part {part}")
        sha = digest(path)
        if stage == "reference":
            crop = self.crops / f"{part}_crop.png"
            if not is_file(crop) or record.get("crop_sha256") != digest(crop):
                raise PipelineError(f"{part}: reference crop changed or is missing; start a new run")
        if sha != record["approved_sha256"]:
            raise PipelineError(f"{part}: approved {stage} SHA changed; use a NEW --run name rather than silently replacing")
        return path

    def plan(self):
        print(f"Approved master: {self.master} (SHA-256 verified)")
        print(f"Anatomical card: {self.card_path}")
        print(f"Quality run: {self.out}")
        print("Reference generation: image-conditioned Qwen Edit 2511 (NOT text-only)")
        print("Geometry: each part reconstructed independently through the existing AI3D backend")
        print("Review gates: reference -> shape -> paint -> game. No automatic approvals.")
        print("Assembly status: anatomical seam landmarks are 2D guides only; no validated 3D stitching/rigging")
        print("\nParts:")
        for part in self.selected():
            statuses = []
            for stage, path in self.paths(part).items():
                rec = self.state["parts"].get(part, {}).get(stage, {})
                if rec.get("approved_sha256") and is_file(path) and digest(path) == rec["approved_sha256"]:
                    status = "approved"
                elif is_file(path):
                    status = "review"
                else:
                    status = "missing"
                statuses.append(f"{stage}={status}")
            print(f"  {part:<14s}  {' | '.join(statuses)}")

    def prepare(self):
        helper = self.root / "legacy/tools/mara_reference_refine.py"
        if not is_file(helper):
            raise PipelineError("Missing legacy/tools/mara_reference_refine.py; install the bundled review helper")
        manifest = self.crops / "reference_parts.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            # Older manifests may not use a standardized key; reject any explicitly wrong digest.
            sha = data.get("master_sha256") or data.get("source_sha256") or data.get("approved_master_sha256")
            if sha != MASTER_SHA:
                raise PipelineError("Reference crop manifest lacks the approved source fingerprint or points to a different image")
            print(f"Review crops already exist: {self.crops}")
            print("These masks/crops are guides; inspect them before reference editing.")
            return
        if self.crops.exists():
            raise PipelineError(f"Crop directory exists without expected manifest: {self.crops}. Inspect rather than overwrite")
        run_command([sys.executable, str(helper), "--input", str(self.master), "--output", str(self.crops)], dry=self.args.dry_run, cwd=self.root)
        print(f"Inspect: {self.crops / 'review.html'}")

    def qwen_cmd(self, part: str, output: Path) -> list[str]:
        # AI3D may symlink its sd.cpp dependency outside the checkout.
        cli_path = Path(self.args.sd_cli).expanduser()
        cli = (self.root / cli_path).resolve() if not cli_path.is_absolute() else cli_path.resolve()
        model_root = Path(self.args.models).expanduser().resolve()
        editor = model_root / self.args.edit_model
        llm = model_root / "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"
        vae = model_root / "qwen_image_vae.safetensors"
        crop = self.crops / f"{part}_crop.png"
        for p in (cli, editor, llm, vae, crop):
            if not p.is_file() or p.stat().st_size == 0:
                raise PipelineError(f"Missing required image-edit dependency: {p}")
        # Keep the prompt positive-only: negated accessory words can produce
        # exactly the objects the user was trying to exclude.
        raw_instructions = self.parts[part]["prompts"]["reference"].strip()
        instructions = ". ".join(
            segment for segment in raw_instructions.split(". ")
            if not segment.strip().lower().startswith(("no ", "avoid ", "without "))
        )
        prompt = (
            f"IMAGE EDIT. Use the FIRST image as the authoritative Mara Venn identity, "
            f"body proportions and costume reference. The SECOND image indicates only the "
            f"{part} region; it is a low-resolution location guide, NOT detailed anatomy. "
            f"Create one isolated, large, high-definition, straight orthographic studio "
            f"reference of {part.replace('_', ' ')}, complete from one attachment seam to the other. "
            f"Maintain anatomical LEFT and RIGHT as seen on the character, not viewer. "
            f"Preserve the green/gray materials and Mara's facial identity, when relevant. "
            f"Preserve the natural geometry of this particular part, including individual "
            f"digits for hands, distinct facial features for the head, and clean "
            f"joint borders, respecting the existing T-pose alignment. One isolated object on a neutral gray studio background. "
            f"{instructions}"
        )
        base = [str(cli), "--diffusion-model", str(editor), "--llm", str(llm),
                "--vae", str(vae), "--backend", "cuda0", "--params-backend", "disk",
                "--max-vram", "-1", "--diffusion-fa", "--cfg-scale", "2.5",
                "--sampling-method", "euler", "--flow-shift", "3",
                "--steps", str(self.args.qwen_steps), "-t", "4",
                "-W", str(self.args.reference_size), "-H", str(self.args.reference_size),
                "--seed", str(self.args.seed),
                "-r", str(self.master), "-r", str(crop), "-p", prompt,
                "-o", str(output)]
        if self.args.dry_run:
            # The deployed binary is not interrogated in dry-run; options are shown.
            base.extend(["--model-args", "qwen_image_zero_cond_t=true"])
        else:
            help_output = subprocess.run([str(cli), "--help"], text=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout
            if "--model-args" in help_output:
                base.extend(["--model-args", "qwen_image_zero_cond_t=true"])
            elif "--qwen-image-zero-cond-t" in help_output:
                base.append("--qwen-image-zero-cond-t")
            else:
                raise PipelineError("sd-cli lacks required Qwen Image Edit 2511 conditioning option; update sd.cpp before GPU work")
        return base

    def generate_reference(self, part: str):
        paths = self.paths(part)
        target = paths["reference"]
        crop = self.crops / f"{part}_crop.png"
        if not is_file(crop):
            raise PipelineError(f"Missing review crop {crop}. Run --stage prepare first")
        if target.exists():
            raise PipelineError(f"Reference already exists: {target}. Inspect/approve; choose a NEW --run for another attempt")
        target.parent.mkdir(parents=True, exist_ok=True) if not self.args.dry_run else None
        cmd = self.qwen_cmd(part, target)
        if self.args.systemd_scope:
            cmd = ["systemd-run", "--user", "--scope", "-p", f"MemoryMax={self.args.ram}",
                   "-p", f"MemorySwapMax={self.args.swap}", *cmd]
        run_command(cmd, dry=self.args.dry_run, cwd=self.root)
        if not self.args.dry_run:
            if not is_file(target):
                raise PipelineError(f"Qwen did not produce {target}")
            self.record(part, "reference").update({"sha256": digest(target), "source_sha256": MASTER_SHA, "crop_sha256": digest(crop)})
            self.write()
            print(f"Inspect {target} (NOT automatically approved)")

    def gpu_stage(self, part: str, stage: str):
        paths = self.paths(part)
        prev = PREVIOUS[stage]
        self.check_approval(part, prev)
        if is_file(paths[stage]):
            raise PipelineError(f"Existing {stage} artifact: {paths[stage]}. Inspect/approve or choose a NEW run")
        src = self.check_approval(part, "reference")
        # Reuse existing verified reference for all downstream inference.
        cmd = [sys.executable, "-m", "ai3d", "generate", "--name", part,
               "--image", str(src), "--output-dir", str(self.out),
               "--stop-after", stage, "--category", "humanoid",
               "--shape-steps", str(self.args.shape_steps),
               "--quality", self.args.quality, "--paint-faces", str(self.args.paint_faces),
               "--game-faces", str(self.args.game_faces),
               "--max-views", str(self.args.max_views),
               "--view-resolution", str(self.args.view_resolution),
               "--texture-size", str(self.args.texture_size),
               "--render-size", str(self.args.render_size),
               "--paint-debug", "--resume"]
        if stage == "shape":
            # Only run the reference/cutout stages in the existing pipeline.
            # Hunyuan inference runs separately with explicit octree controls;
            # never write into a third-party Hunyuan checkout.
            cut_cmd = cmd.copy()
            cut_cmd[cut_cmd.index("--stop-after") + 1] = "cutout"
            run_command(cut_cmd, dry=self.args.dry_run, cwd=self.root)
            hunyuan = self.root / "Hunyuan3D-2"
            hy_python = hunyuan / ".venv/bin/python"
            script = self.root / "legacy/tools/hunyuan_detail_shape.py"
            if not is_file(script) or not hy_python.is_file():
                raise PipelineError(f"Missing Hunyuan wrapper or virtualenv: {script} / {hy_python}")
            env = os.environ.copy()
            env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
            high_detail_cmd = [str(hy_python), str(script), "--input", str(self.out / part / "02_cutout.png"),
                "--output", str(paths["shape"]), "--model-dir", str(self.root / "models/Hunyuan3D-2mini"),
                "--steps", str(self.args.shape_steps), "--octree-resolution", str(self.args.octree_resolution),
                "--chunks", str(self.args.chunks), "--seed", str(self.args.seed)]
            run_command(high_detail_cmd, dry=self.args.dry_run, cwd=self.root, env=env)
        else:
            # Keep the raw high-detail reconstruction intact; the AI3D
            # pipeline must never silently reconstruct/replace it.
            cmd.extend(["--shape-mesh", str(self.check_approval(part, "shape"))])
            run_command(cmd, dry=self.args.dry_run, cwd=self.root)
        if not self.args.dry_run:
            if not is_file(paths[stage]):
                raise PipelineError(f"Expected stage output not found: {paths[stage]}")
            self.record(part, stage).update({"sha256": digest(paths[stage]), "source_reference_sha256": digest(src)})
            self.write()
            print(f"Inspect {paths[stage]} (NOT automatically approved)")
            if stage == "shape":
                print(f"Optional renders: --stage review --part {part}")

    def approve(self, part: str):
        stage = self.args.approve
        if not stage:
            raise PipelineError("Use --stage approve --approve reference|shape|paint|game")
        path = self.paths(part)[stage]
        if not is_file(path):
            raise PipelineError(f"Cannot approve absent artifact {path}")
        if stage in PREVIOUS:
            self.check_approval(part, PREVIOUS[stage])
        rec = self.state["parts"].get(part, {}).get(stage)
        if not rec or rec.get("sha256") != digest(path):
            raise PipelineError("Artifact differs from recorded stage output or was not produced by this driver")
        if self.args.dry_run:
            print(f"Would approve {part} {stage}: {digest(path)}")
            return
        rec["approved_sha256"] = digest(path)
        rec["approved_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.write()
        print(f"APPROVED {part} {stage} {rec['approved_sha256']}")

    def review(self, part: str):
        shape = self.paths(part)["shape"]
        if not is_file(shape):
            raise PipelineError("Shape is missing; reconstruct it before rendering review views")
        script = self.root / "legacy/tools/mara_quality_mesh_review.py"
        if not is_file(script):
            raise PipelineError(f"Missing Blender review helper: {script}")
        out = self.out / part / "mesh_review"
        if out.exists():
            raise PipelineError(f"Review already exists: {out}; do not overwrite it")
        run_command(["blender", "--background", "--factory-startup", "--python-exit-code", "1",
                    "--python", str(script), "--", "--mesh", str(shape),
                    "--output", str(out)], cwd=self.root, dry=self.args.dry_run)
        print(f"Inspect front, back, side and 3/4 images in {out}")

    def fit_audit(self):
        print("FITTING AUDIT: only 2-D seam landmarks and assumed-depth prototypes exist.")
        for script in ("legacy/tools/mara_attachment_scaffold.py", "legacy/tools/mara_depth_proxy.py"):
            helper = self.root / script
            if not helper.exists():
                print(f"NOT INSTALLED: {script}")
                continue
            run_command([sys.executable, str(helper), "--audit-only"], cwd=self.root, dry=self.args.dry_run)
        print("3-D seam welding, topology transfer and armature weighting remain UNVALIDATED; no export permitted.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--card", default=DEFAULT_CARD)
    p.add_argument("--run", default="mara_quality_v1", help="New unique name for each experiment; never overwrite prior runs")
    p.add_argument("--stage", required=True, choices=("plan", "prepare", "reference", "shape", "paint", "game", "review", "approve", "fit-audit"))
    choice = p.add_mutually_exclusive_group(required=False)
    choice.add_argument("--part", action="append")
    choice.add_argument("--all-parts", action="store_true")
    p.add_argument("--approve", choices=STAGES)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sd-cli", default="stable-diffusion.cpp/build/bin/sd-cli")
    p.add_argument("--models", default=str(Path.home() / "models/Qwen-Image-2512"))
    p.add_argument("--edit-model", default="qwen-image-edit-2511-Q3_K_M.gguf")
    p.add_argument("--reference-size", type=int, default=768)
    p.add_argument("--qwen-steps", type=int, default=40)
    p.add_argument("--shape-steps", type=int, default=50)
    p.add_argument("--octree-resolution", type=int, default=256)
    p.add_argument("--chunks", type=int, default=4000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--paint-faces", type=int, default=120000)
    p.add_argument("--game-faces", type=int, default=60000)
    p.add_argument("--quality", choices=("fast", "low", "medium", "high", "highest"), default="high")
    p.add_argument("--max-views", type=int, default=4)
    p.add_argument("--view-resolution", type=int, default=512)
    p.add_argument("--texture-size", type=int, default=2048)
    p.add_argument("--render-size", type=int, default=768)
    p.add_argument("--systemd-scope", action="store_true", default=True)
    p.add_argument("--no-systemd-scope", dest="systemd_scope", action="store_false")
    p.add_argument("--ram", default="12G")
    p.add_argument("--swap", default="4G")
    args = p.parse_args(argv)
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", args.run):
        p.error("--run must be a 3-64 character lower_snake_case name")
    if any(getattr(args, n) < 1 for n in ("reference_size", "qwen_steps", "shape_steps", "octree_resolution", "chunks", "paint_faces", "game_faces", "max_views", "view_resolution", "texture_size", "render_size")):
        p.error("dimensions, steps, and target counts must be positive")
    try:
        workflow = QualityWorkflow(args)
        if args.stage == "prepare":
            workflow.prepare()
        elif args.stage == "fit-audit":
            workflow.fit_audit()
        elif args.stage == "plan":
            workflow.plan()
        else:
            selected = workflow.selected()
            for part in selected:
                print(f"\n=== {part}: {args.stage} ===", flush=True)
                if args.stage == "reference":
                    workflow.generate_reference(part)
                elif args.stage in STAGES:
                    workflow.gpu_stage(part, args.stage)
                elif args.stage == "review":
                    workflow.review(part)
                elif args.stage == "approve":
                    workflow.approve(part)
        return 0
    except (OSError, PipelineError, ValueError, subprocess.CalledProcessError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
