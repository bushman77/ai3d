"""Orchestration tests for pipelines/image_to_3d.py (no GPU, no Blender)."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from ai3d.blender.commands import blender_command
from ai3d.geometry.hunyuan import build_hunyuan_shape_command
from ai3d.image.qwen import build_qwen_edit_command, view_prompt
from ai3d.pipeline_runner import Runner
from pipelines.image_to_3d import STAGES, main, warnings_for


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(list(argv))
    return out.getvalue()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.image = self.dir / "front.png"
        self.image.write_bytes(b"png")
        self.outputs = self.dir / "outputs"

    def tearDown(self):
        self.tmp.cleanup()

    def test_stage_order(self):
        self.assertEqual(STAGES, ("reference", "views", "cutout", "shape", "paint-mesh",
                                  "paint", "texture-views", "game", "rig", "report"))

    def test_dry_run_plans_every_stage_and_writes_nothing(self):
        text = run("--name", "plan", "--image", str(self.image),
                   "--output-dir", str(self.outputs), "--dry-run")
        for label in ("views-left", "views-back", "views-right", "cutout-back", "shape",
                      "paint-mesh", "paint", "texture-views-front", "texture-views-back",
                      "texture-cutout-left", "game", "rig", "report-game", "report-rigged"):
            self.assertIn(f"[PLAN] {label}", text)
        self.assertIn("--model mv", text)
        self.assertIn("retopo_bake.py", text)
        self.assertIn("rig.py", text)
        game = text.split("[PLAN] game")[1].split("[PLAN]")[0]
        for kind in ("front", "left", "back", "right"):
            self.assertIn(f"--view {kind}=", game)
            self.assertIn(f"02_hd_cutout_{kind}.png", game)
        self.assertFalse(self.outputs.exists())

    def test_texture_views_can_use_plain_cutouts_or_be_off(self):
        text = run("--name", "p", "--image", str(self.image), "--output-dir", str(self.outputs),
                   "--set", "texture_views.upscale=false", "--dry-run")
        self.assertNotIn("texture-views-front", text)
        game = text.split("[PLAN] game")[1].split("[PLAN]")[0]
        self.assertIn("front=", game)
        self.assertIn("02_cutout_back.png", game)
        text = run("--name", "p", "--image", str(self.image), "--output-dir", str(self.outputs),
                   "--set", "texture_views.enabled=false", "--dry-run")
        self.assertNotIn("--view front", text)

    def test_no_views_uses_single_view_model(self):
        text = run("--name", "p", "--image", str(self.image), "--no-views",
                   "--output-dir", str(self.outputs), "--dry-run")
        self.assertIn("--model mini", text)
        self.assertNotIn("views-left", text)
        self.assertNotIn("--left", text)

    def test_own_views_are_used_without_qwen(self):
        back = self.dir / "back.png"
        back.write_bytes(b"b")
        text = run("--name", "p", "--image", str(self.image), "--view-back", str(back),
                   "--set", 'views.angles=["back"]',
                   "--output-dir", str(self.outputs), "--dry-run")
        self.assertNotIn("[PLAN] views-back", text)  # a copy, not a Qwen command
        self.assertIn("--back", text)
        self.assertIn("--model mv", text)

    def test_disabled_stages_are_skipped(self):
        text = run("--name", "p", "--image", str(self.image), "--no-views", "--no-rig",
                   "--no-retopo", "--output-dir", str(self.outputs), "--dry-run")
        self.assertNotIn("rig.py", text)
        self.assertNotIn("retopo_bake.py", text)
        self.assertIn("blender_finalize.py", text)
        self.assertNotIn("report-rigged", text)

    def test_preflight_stops_before_any_work_when_tools_missing(self):
        with self.assertRaisesRegex(RuntimeError, "Missing tools/models"):
            run("--name", "p", "--image", str(self.image), "--output-dir", str(self.outputs),
                "--set", f"paths.hunyuan={self.dir / 'nope'}",
                "--set", f"paths.blender={self.dir / 'no-blender'}")
        self.assertFalse((self.outputs / "p").exists())

    def test_reference_only_copies_image(self):
        run("--name", "r", "--image", str(self.image), "--output-dir", str(self.outputs),
            "--stop-after", "reference")
        self.assertEqual((self.outputs / "r/01_reference.png").read_bytes(), b"png")
        self.assertTrue((self.outputs / "r/settings.json").is_file())

    def test_input_validation(self):
        with self.assertRaisesRegex(RuntimeError, "Provide --image"):
            run("--name", "x", "--dry-run")
        with self.assertRaisesRegex(RuntimeError, "needs --image"):
            run("--name", "x", "--shape-mesh", str(self.image), "--painted-mesh",
                str(self.image), "--dry-run")
        with self.assertRaisesRegex(RuntimeError, "front --image"):
            run("--name", "x", "--painted-mesh", str(self.image), "--view-back",
                str(self.image), "--dry-run")

    def test_warnings(self):
        self.assertEqual(warnings_for({}), [])
        w = warnings_for({
            "quality_game": {"silhouette_iou": 0.6, "mesh": {"pieces": 3, "boundary_edges": 5}},
            "game": {"method": "decimate (quadriflow failed)", "surface_error_max": 0.05,
                     "low_pieces": 3, "shape_pieces": 1,
                     "projected_views": [{"view": "back", "skipped": True}]},
            "rig": {"unweighted_after_heat_fraction": 0.1, "arm_leak": 0.4,
                    "shoulder_height_fraction": 0.6, "hip_height_fraction": 0.3, "facing_detected": "unknown (assumed -Y)",
                    "deform_bones_without_vertices": ["mixamorig:LeftToeBase"]},
        })
        text = " | ".join(w)
        for needle in ("silhouette", "3 separate pieces", "holes", "QuadriFlow failed", "limb came loose", "not projected",
                       "misses detail", "automatic weights", "below the armpits", "shoulder joints", "hip joint", "faces", "LeftToeBase"):
            self.assertIn(needle, text)


class AspectTests(unittest.TestCase):
    def test_edit_dims_keep_the_reference_shape(self):
        from ai3d.image.size import edit_dims, image_size
        self.assertEqual(edit_dims((512, 512), 512), (512, 512))
        self.assertEqual(edit_dims((512, 768), 512), (448, 640))   # portrait stays portrait
        self.assertEqual(edit_dims((512, 768), 1024), (832, 1280))
        self.assertEqual(edit_dims(None, 1024), (1024, 1024))
        mara = Path(__file__).resolve().parent.parent / "approved_references/mara_body_front_approved.png"
        self.assertEqual(image_size(mara), (512, 512))

    def test_portrait_prompt_reference_gives_portrait_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prompt = tmp / "p.txt"
            prompt.write_text("A pilot.")
            text = run("--name", "x", "--prompt-file", str(prompt), "--output-dir", str(tmp / "o"),
                       "--dry-run")
            back = text.split("[PLAN] views-back")[1].split("[PLAN]")[0]
            self.assertIn("-W 448 -H 640", back)
            hd = text.split("[PLAN] texture-views-front")[1].split("[PLAN]")[0]
            self.assertIn("-W 832 -H 1280", hd)

    def test_cut_off_warning(self):
        w = warnings_for({"cutouts": {"cut_off": {"back": ["top"]}}})
        self.assertTrue(any("back picture is cut off at the top" in x for x in w))


class PromptSplitTests(unittest.TestCase):
    def test_negative_prompt_is_separated(self):
        from ai3d.image.qwen import split_prompt
        pos, neg = split_prompt("A pilot.\n\nFull body.\n\n**Negative prompt:**\n\nNo backpack, no text.")
        self.assertEqual(pos, "A pilot.\n\nFull body.")
        self.assertEqual(neg, "No backpack, no text.")
        self.assertEqual(split_prompt("Negative prompt: no hats\n")[1], "no hats")
        self.assertEqual(split_prompt("just a prompt"), ("just a prompt", ""))

    def test_reference_command_gets_negative_prompt_and_redo_front(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prompt = tmp / "p.txt"
            prompt.write_text("A pilot.\n**Negative prompt:** no backpack")
            text = run("--name", "x", "--prompt-file", str(prompt), "--output-dir", str(tmp / "o"),
                       "--stop-after", "reference", "--dry-run", "--redo-view", "front")
            ref = text.split("[PLAN] reference")[1]
            self.assertIn("-n 'no backpack'", ref.replace('"', "'"))
            self.assertNotIn("no backpack", ref.split(" -n ")[0])
            self.assertIn("[redo] front image with seed", text)
            with self.assertRaisesRegex(RuntimeError, "only works with --prompt-file"):
                run("--name", "y", "--image", str(prompt), "--output-dir", str(tmp / "o"),
                    "--redo-view", "front", "--dry-run")


class BuilderTests(unittest.TestCase):
    def test_qwen_edit_uses_reference_and_vision_encoder(self):
        cmd = build_qwen_edit_command(
            Path("/sd"), diffusion_model=Path("/m/edit.gguf"), llm=Path("/m/llm.gguf"),
            llm_vision=Path("/m/mmproj.gguf"), vae=Path("/m/vae.st"), reference=Path("/r.png"),
            prompt=view_prompt("back"), output=Path("/o.png"), seed=7)
        self.assertEqual(cmd[cmd.index("-r") + 1], "/r.png")
        self.assertEqual(cmd[cmd.index("--llm_vision") + 1], "/m/mmproj.gguf")
        self.assertEqual(cmd[cmd.index("--seed") + 1], "7")
        self.assertIn("--vae-tiling", cmd)
        prompt = cmd[len(cmd) - 1 - cmd[::-1].index("-p") + 1]  # last -p (first is systemd's)
        self.assertIn("behind", prompt)
        with self.assertRaises(ValueError):
            view_prompt("top")

    def test_hunyuan_shape_builder_validates_view_model_pairing(self):
        cmd = build_hunyuan_shape_command(Path("/py"), Path("/s.py"), Path("/o.glb"),
                                          front=Path("/f.png"), back=Path("/b.png"), model="mv")
        self.assertIn("--back", cmd)
        with self.assertRaises(ValueError):
            build_hunyuan_shape_command(Path("/py"), Path("/s.py"), Path("/o.glb"),
                                        front=Path("/f.png"), model="mv")
        with self.assertRaises(ValueError):
            build_hunyuan_shape_command(Path("/py"), Path("/s.py"), Path("/o.glb"),
                                        front=Path("/f.png"), back=Path("/b.png"), model="mini")

    def test_blender_command_only_known_scripts(self):
        cmd = blender_command("blender", "rig.py", ["--input", Path("/a.glb")])
        self.assertEqual(cmd[:2], ["blender", "--background"])
        self.assertEqual(cmd[-2:], ["--input", "/a.glb"])
        with self.assertRaises(ValueError):
            blender_command("blender", "nope.py", [])

    def test_runner_dry_run_prints_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Runner(Path(tmp), False, False, True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                r.run_cmd("x", [], [Path(tmp) / "o"], {}, ["echo", Path("/p q")])
            self.assertIn("[PLAN] x", out.getvalue())
            self.assertIn('"/p q"', out.getvalue())


if __name__ == "__main__":
    unittest.main()


class RedoViewTests(unittest.TestCase):
    def test_redo_view_only_reruns_that_view_with_new_seed(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            image = tmp / "front.png"
            image.write_bytes(b"png")
            home = tmp / "out" / "r"
            home.mkdir(parents=True)
            for angle in ("left", "back", "right"):
                (home / f"01_view_{angle}.png").write_bytes(b"old")
            fake_sd = tmp / "sd-cli"
            fake_sd.write_text("")
            models = tmp / "m"
            models.mkdir()
            for name in ("edit.gguf", "mm.gguf", "llm.gguf", "vae.st"):
                (models / name).write_bytes(b"x")
            common = ["--name", "r", "--image", str(image), "--output-dir", str(tmp / "out"),
                      "--set", f"paths.sd_cli={fake_sd}",
                      "--set", f"paths.qwen_model_dir={models}",
                      "--set", f"paths.qwen_edit_model_dir={models}",
                      "--set", "views.diffusion_model=edit.gguf",
                      "--set", "views.llm_vision=mm.gguf",
                      "--set", "reference.llm=llm.gguf", "--set", "reference.vae=vae.st"]
            text = run(*common, "--redo-view", "back", "--dry-run")
            self.assertIn("[redo] back view with seed", text)
            self.assertTrue((home / "01_view_back.png").exists())  # dry run deletes nothing
            with self.assertRaisesRegex(RuntimeError, "conflicts"):
                run(*common, "--redo-view", "back", "--view-back", str(image), "--dry-run")
            seeds = {"back": 123}
            (home / "view_seeds.json").write_text(json.dumps(seeds))
            text = run(*common, "--dry-run")
            back_cmd = text.split("[PLAN] views-back")[1].split("[PLAN]")[0]
            left_cmd = text.split("[PLAN] views-left")[1].split("[PLAN]")[0]
            self.assertIn("--seed 123", back_cmd)
            self.assertIn("--seed 42", left_cmd)
            self.assertIn("feet point away", back_cmd)
