"""Regressions for sequential card-driven character asset generation.

No CUDA, Qwen, Hunyuan, Blender or Paint3D processes are started in these
tests. The model subprocess boundaries are deliberately mocked.
"""

from copy import deepcopy
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, call

from ai3d.characters.batch import build_plan, generate_character
from ai3d.characters.card import ROOT, load_card
from pipelines.image_to_3d import main as pipeline_main

MARA = ROOT / "examples/space_nova/characters/mara_venn.json"


class CharacterBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "outputs"
        self.card = load_card(MARA)

    def plan(self, **opts):
        return build_plan(self.card, output_dir=self.root, **opts)

    def run(self, **opts):
        args = dict(
            output_dir=self.root,
            sd_cli=Path("/fake/sd-cli"),
            qwen_model_dir=Path("/fake/qwen"),
            dry_run=True,
        )
        args.update(opts)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            plan = generate_character(self.card, MARA, **args)
        return plan, out.getvalue()

    def test_plan_all_six_parts_in_card_order(self):
        plan = self.plan(all_parts=True)
        self.assertEqual(
            [p["part_id"] for p in plan],
            ["body", "head", "hair", "outfit", "hands", "equipment"],
        )
        self.assertEqual(len({p["folder"] for p in plan}), 6)

    def test_default_stops_at_reference_for_every_part(self):
        plan = self.plan(all_parts=True)
        self.assertEqual({p["stage"] for p in plan}, {"reference"})

    def test_regions_stop_at_reference_by_default(self):
        plan = self.plan(all_parts=True, stop_after="game")
        stage = {p["part_id"]: p["stage"] for p in plan}
        self.assertEqual(stage["body"], "game")
        self.assertEqual(stage["head"], "game")
        self.assertEqual(stage["equipment"], "game")
        for name in ("hair", "hands", "outfit"):
            self.assertEqual(stage[name], "reference")

    def test_include_regions_enables_isolated_mesh_trials(self):
        plan = self.plan(all_parts=True, include_regions=True, stop_after="paint")
        self.assertEqual({p["stage"] for p in plan}, {"paint"})

    def test_skip_previously_approved_head(self):
        plan = self.plan(all_parts=True, skip=["head"], stop_after="shape")
        self.assertNotIn("head", [p["part_id"] for p in plan])
        self.assertEqual(len(plan), 5)

    def test_select_individual_parts_preserves_card_order_requested(self):
        plan = self.plan(part_ids=["equipment", "head", "equipment"])
        self.assertEqual([p["part_id"] for p in plan], ["equipment", "head"])

    def test_unique_run_prefix_keeps_separate_output_folders(self):
        plan = self.plan(all_parts=True, run_prefix="mara_complete_v1")
        self.assertEqual(plan[1]["name"], "mara_complete_v1_head_head_closeup")
        self.assertEqual(plan[1]["folder"], self.root / plan[1]["name"])

    def test_invalid_part_and_prefix_fail_before_inference(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown part"):
            self.plan(part_ids=["wings"])
        with self.assertRaisesRegex(RuntimeError, "name must contain"):
            self.plan(all_parts=True, run_prefix="../outside")

    def test_empty_selection_and_conflicting_selection_fail(self):
        with self.assertRaisesRegex(RuntimeError, "Select either"):
            self.plan()
        with self.assertRaisesRegex(RuntimeError, "Select either"):
            self.plan(all_parts=True, part_ids=["head"])
        with self.assertRaisesRegex(RuntimeError, "No parts selected"):
            self.plan(part_ids=["head"], skip=["head"])

    def test_missing_part_reference_rejected_before_generation(self):
        card = deepcopy(self.card)
        card["parts"][1]["prompts"]["reference"] = ""
        with self.assertRaisesRegex(RuntimeError, "prompts.reference"):
            build_plan(card, part_ids=["head"], output_dir=self.root)

    def test_unsupported_geometry_or_texture_backends_rejected(self):
        card = deepcopy(self.card)
        card["parts"][1]["generation"]["geometry_backend"] = "unknown"
        with self.assertRaisesRegex(RuntimeError, "unsupported geometry_backend"):
            build_plan(card, part_ids=["head"], stop_after="shape", output_dir=self.root)
        card["parts"][1]["generation"]["geometry_backend"] = "hunyuan"
        card["parts"][1]["generation"]["texture_backend"] = "unknown"
        with self.assertRaisesRegex(RuntimeError, "unsupported texture_backend"):
            build_plan(card, part_ids=["head"], stop_after="paint", output_dir=self.root)

    def test_dry_run_prints_plan_and_creates_no_files(self):
        plan, output = self.run(all_parts=True, stop_after="game")
        self.assertEqual(len(plan), 6)
        self.assertIn("Region parts produce references only", output)
        self.assertIn("Dry run completed", output)
        self.assertFalse(self.root.exists())

    def test_preflight_refuses_existing_dir_before_starting_any_model(self):
        (self.root / "mara_venn_head_head_closeup").mkdir(parents=True)
        with patch("ai3d.characters.batch.run_reference") as mocked:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                self.run(all_parts=True, dry_run=False)
            mocked.assert_not_called()

    def test_existing_outputs_are_allowed_with_resume(self):
        (self.root / "mara_venn_head_head_closeup").mkdir(parents=True)
        plan, _ = self.run(part_ids=["head"], resume=True)
        self.assertEqual(len(plan), 1)

    def test_symlinked_output_run_is_refused(self):
        external = Path(self.tmp.name) / "elsewhere"
        external.mkdir()
        self.root.mkdir()
        (self.root / "mara_venn_head_head_closeup").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.run(part_ids=["head"])

    def test_dry_run_does_not_call_full_pipeline(self):
        with patch("pipelines.image_to_3d.main") as pipeline:
            self.run(all_parts=True, stop_after="game")
        pipeline.assert_not_called()

    def test_generates_parts_sequentially_and_passes_settings(self):
        recorded = []
        def fake_reference(_card, _card_path, **kwargs):
            recorded.append(("reference", kwargs["part_id"]))
            return Path("/test/01_reference.png")
        def fake_pipeline(args, prog=None):
            recorded.append(("pipeline", args[args.index("--name") + 1]))
        with patch("ai3d.characters.batch.run_reference", side_effect=fake_reference):
            with patch("pipelines.image_to_3d.main", side_effect=fake_pipeline):
                with contextlib.redirect_stdout(io.StringIO()):
                    generate_character(
                        self.card, MARA, all_parts=True,
                        stop_after="paint", output_dir=self.root,
                        sd_cli=Path("/fake/sd-cli"), qwen_model_dir=Path("/fake/qwen"),
                        dry_run=False,
                    )
        self.assertEqual(recorded, [
            ("reference", "body"),
            ("pipeline", "mara_venn_body_front"),
            ("reference", "head"),
            ("pipeline", "mara_venn_head_head_closeup"),
            ("reference", "hair"),
            ("reference", "outfit"),
            ("reference", "hands"),
            ("reference", "equipment"),
            ("pipeline", "mara_venn_equipment_three_quarter"),
        ])

    def test_user_part_settings_override_global_defaults(self):
        card = deepcopy(self.card)
        head = card["parts"][1]
        head["generation"].update({
            "shape_steps": 50,
            "target_triangles": 75000,
            "view_resolution": 384,
        })
        captured = []
        def fake_reference(_card, _path, **kwargs):
            return Path("/ref.png")
        def fake_pipeline(argv, prog=None):
            captured.extend(argv)
        with patch("ai3d.characters.batch.run_reference", side_effect=fake_reference):
            with patch("pipelines.image_to_3d.main", side_effect=fake_pipeline):
                with contextlib.redirect_stdout(io.StringIO()):
                    generate_character(
                        card, MARA, part_ids=["head"], stop_after="paint",
                        output_dir=self.root, dry_run=False,
                    )
        self.assertEqual(captured[captured.index("--shape-steps") + 1], "50")
        self.assertEqual(captured[captured.index("--paint-faces") + 1], "75000")
        self.assertEqual(captured[captured.index("--view-resolution") + 1], "384")
        self.assertIn("--resume", captured)

    def test_force_and_resume_conflict(self):
        with self.assertRaisesRegex(RuntimeError, "either --resume or --force"):
            self.run(part_ids=["head"], resume=True, force=True)

    def test_invalid_positive_options_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "positive"):
            self.run(part_ids=["head"], qwen_width=-1)

    def test_cli_help_includes_all_and_parts(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "generate", "--help"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--all", "--part", "--skip", "--include-regions", "--run-prefix"):
            self.assertIn(option, result.stdout)

    def test_cli_dry_run_smoke(self):
        result = subprocess.run(
            [
                sys.executable, "-m", "ai3d", "character", "generate",
                str(MARA), "--all", "--stop-after", "shape",
                "--run-prefix", "mara_batch_test",
                "--output-dir", str(self.root), "--dry-run",
            ],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mara_batch_test_head_head_closeup", result.stdout)
        self.assertFalse(self.root.exists())

    def test_in_place_reference_does_not_overwrite_qwen_cache_stamp(self):
        output = self.root / "sample"
        (output / ".stages").mkdir(parents=True)
        reference = output / "01_reference.png"
        reference.write_bytes(b"existing Qwen output")
        stamp = output / ".stages/reference.json"
        stamp.write_text('{"fingerprint": "qwen-cache-intact"}')
        with contextlib.redirect_stdout(io.StringIO()) as display:
            pipeline_main([
                "--name", "sample",
                "--image", str(reference),
                "--output-dir", str(self.root),
                "--stop-after", "reference",
            ])
        self.assertIn("[REUSE] reference already in run", display.getvalue())
        self.assertEqual(stamp.read_text(), '{"fingerprint": "qwen-cache-intact"}')
        self.assertEqual(reference.read_bytes(), b"existing Qwen output")


if __name__ == "__main__":
    unittest.main()
