"""Character card -> Qwen image-reference stage contract, without GPU inference."""

from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai3d.characters.card import ROOT, load_card, new_card, validate_card
from ai3d.characters.reference import (
    select_part_and_view, compose_reference_prompt, run_reference,
)
from ai3d.pipeline_runner import Runner

MARA = ROOT / "examples/space_nova/characters/mara_venn.json"


class CharacterReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.output = self.folder / "outputs"
        self.card = load_card(MARA)
        self.sd = self.folder / "sd-cli"
        self.weights = self.folder / "qwen"
        self.args = dict(
            part_id="head", output_dir=self.output,
            sd_cli=self.sd, model_dir=self.weights,
        )

    def create_fake_dependencies(self):
        self.sd.write_text("#!/bin/sh\nexit 0\n")
        self.sd.chmod(0o755)
        self.weights.mkdir()
        for filename in (
            "qwen-image-2512-Q3_K_M.gguf",
            "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
            "qwen_image_vae.safetensors",
        ):
            (self.weights / filename).write_bytes(b"tiny-test-weight")

    def fake_generate(self, runner, label, command, cwd=None, env=None):
        self.assertEqual(label, "reference")
        self.assertIn("--backend", command)
        Path(command[command.index("-o") + 1]).write_bytes(b"mock-png")

    def test_template_and_example_have_valid_part_reference_fields(self):
        self.assertEqual(validate_card(new_card("my_new_character")), [])
        self.assertEqual(validate_card(self.card), [])
        self.assertTrue(all(p.get("reference_view") for p in self.card["parts"]))
        self.assertTrue(all(p["prompts"].get("reference") for p in self.card["parts"]))

    def test_head_prompt_rejects_master_full_body_framing(self):
        part, view = select_part_and_view(self.card, "head")
        self.assertEqual(view, "head_closeup")
        prompt = compose_reference_prompt(self.card, part, view)
        self.assertIn("Mara Venn", prompt)
        self.assertIn("eyelids", prompt)
        self.assertIn("head-and-neck", prompt)
        self.assertNotIn("Entire character in frame", prompt)
        self.assertNotIn("no cropped body parts", prompt)
        self.assertIn("No full body", prompt)

    def test_body_uses_its_own_reference_prompt(self):
        part, view = select_part_and_view(self.card, "body")
        self.assertEqual(view, "front")
        prompt = compose_reference_prompt(self.card, part, view)
        self.assertIn("A-pose", prompt)
        self.assertIn("entire body", prompt.lower())
        self.assertNotIn("avoid:", prompt.lower())

    def test_mara_body_revision_five_has_visual_only_clean_reference(self):
        part, view = select_part_and_view(self.card, "body")
        prompt = compose_reference_prompt(self.card, part, view)
        self.assertEqual(self.card["revision"], 5)
        self.assertEqual(part["generation"]["reference_mode"], "visual_only")
        self.assertIn("natural bust", self.card["prompts"]["master"])
        self.assertIn("athletic feminine", prompt)
        self.assertIn("continuous", prompt)
        self.assertIn("jumpsuit", prompt)
        self.assertNotIn("Avoid:", prompt)
        self.assertNotIn("repair engineer", prompt)
        self.assertNotIn("utility belt", prompt)
        self.assertEqual(validate_card(self.card), [])

    def test_mara_split_outfit_references_are_independent_and_positive_only(self):
        parts = {part["id"]: part for part in self.card["parts"]}
        self.assertNotIn("outfit", parts)
        self.assertEqual(parts["upper_outfit"]["kind"], "region")
        self.assertEqual(parts["lower_outfit"]["kind"], "region")
        for ident, own, other in (
            ("upper_outfit", "collar", "trouser legs"),
            ("lower_outfit", "trousers", "both sleeves"),
        ):
            part, view = select_part_and_view(self.card, ident)
            prompt = compose_reference_prompt(self.card, part, view)
            self.assertEqual(part["generation"]["reference_mode"], "visual_only")
            self.assertIn(own, prompt.lower())
            self.assertNotIn("Avoid:", prompt)
            self.assertNotIn("Personality:", prompt)
            self.assertNotIn("utility belt", prompt.lower())
            self.assertNotIn(other, part["prompts"]["reference"].lower())
            self.assertEqual(part["parent"], "body")
            self.assertEqual(part["reference_view"], view)
        self.assertEqual(validate_card(self.card), [])

    def test_invalid_reference_mode_is_rejected(self):
        altered = deepcopy(self.card)
        altered["parts"][0]["generation"]["reference_mode"] = "unrecognized"
        self.assertTrue(any("reference_mode" in error for error in validate_card(altered)))

    def test_missing_dedicated_reference_prompt_rejected(self):
        card = new_card("any_character")
        card["prompts"]["reference_views"]["head_closeup"] = "Front head close-up."
        part, view = select_part_and_view(card, "head")
        with self.assertRaisesRegex(RuntimeError, "prompts.reference"):
            compose_reference_prompt(card, part, view)

    def test_unknown_part_and_view_explained(self):
        with self.assertRaisesRegex(RuntimeError, "no part"):
            select_part_and_view(self.card, "wings")
        with self.assertRaisesRegex(RuntimeError, "No reference instructions"):
            select_part_and_view(self.card, "head", "missing_view")

    def test_card_validator_rejects_undefined_reference_view(self):
        card = deepcopy(self.card)
        card["parts"][1]["reference_view"] = "not_real"
        self.assertTrue(any("reference_view" in err for err in validate_card(card)))

    def test_dry_run_is_read_only_without_models(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            image = run_reference(self.card, MARA, dry_run=True, **self.args)
        self.assertEqual(image, self.output / "mara_venn_head_head_closeup/01_reference.png")
        self.assertIn("eyelids", buffer.getvalue())
        self.assertIn("systemd-run", buffer.getvalue())
        self.assertIn("no files generated", buffer.getvalue().lower())
        self.assertFalse(self.output.exists())

    def test_dry_run_works_against_existing_output(self):
        target = self.output / "mara_venn_head_head_closeup"
        target.mkdir(parents=True)
        with contextlib.redirect_stdout(io.StringIO()):
            run_reference(self.card, MARA, dry_run=True, **self.args)
        self.assertEqual(list(target.iterdir()), [])

    def test_real_run_requires_explicit_resume_for_existing_folder(self):
        (self.output / "mara_venn_head_head_closeup").mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "already|exists"):
            run_reference(self.card, MARA, **self.args)

    def test_run_writes_prompt_manifest_and_generated_file(self):
        self.create_fake_dependencies()
        with patch.object(Runner, "command", autospec=True, side_effect=self.fake_generate):
            with contextlib.redirect_stdout(io.StringIO()):
                image = run_reference(self.card, MARA, **self.args)
        self.assertEqual(image.read_bytes(), b"mock-png")
        root = image.parent
        prompt = (root / "reference_prompt.txt").read_text()
        metadata = json.loads((root / "reference_manifest.json").read_text())
        self.assertEqual(metadata["character_id"], "mara_venn")
        self.assertEqual(metadata["part"], "head")
        self.assertEqual(metadata["view"], "head_closeup")
        self.assertEqual(metadata["settings"]["width"], 384)
        self.assertIn("eyelids", prompt)
        self.assertTrue((root / ".stages/reference.json").is_file())

    def test_resume_with_identical_inputs_reuses_reference(self):
        self.create_fake_dependencies()
        with patch.object(Runner, "command", autospec=True, side_effect=self.fake_generate) as cmd:
            with contextlib.redirect_stdout(io.StringIO()):
                image = run_reference(self.card, MARA, **self.args)
                second = run_reference(self.card, MARA, resume=True, **self.args)
        self.assertEqual(image, second)
        self.assertEqual(cmd.call_count, 1)

    def test_changed_prompt_invalidates_resume_cache(self):
        self.create_fake_dependencies()
        changed = deepcopy(self.card)
        changed["parts"][1]["prompts"]["reference"] += " Emphasize the eyelid crease."
        with patch.object(Runner, "command", autospec=True, side_effect=self.fake_generate) as cmd:
            with contextlib.redirect_stdout(io.StringIO()):
                run_reference(self.card, MARA, **self.args)
                run_reference(changed, MARA, resume=True, **self.args)
        self.assertEqual(cmd.call_count, 2)

    def test_reject_run_symlink(self):
        external = self.folder / "external"
        external.mkdir()
        self.output.mkdir()
        (self.output / "mara_venn_head_head_closeup").symlink_to(
            external, target_is_directory=True
        )
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            run_reference(self.card, MARA, dry_run=True, **self.args)

    def test_reject_output_file_symlink(self):
        target = self.output / "mara_venn_head_head_closeup"
        target.mkdir(parents=True)
        external = self.folder / "external.png"
        external.write_bytes(b"do not overwrite")
        (target / "01_reference.png").symlink_to(external)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            run_reference(self.card, MARA, resume=True, **self.args)
        self.assertEqual(external.read_bytes(), b"do not overwrite")

    def test_invalid_resolution_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "positive"):
            run_reference(self.card, MARA, width=0, dry_run=True, **self.args)

    def test_command_line_dry_run(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "reference", str(MARA),
             "--part", "head", "--output-dir", str(self.output), "--dry-run"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("head_closeup", result.stdout)
        self.assertFalse(self.output.exists())

    def test_command_line_error_on_missing_part(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "reference", str(MARA),
             "--part", "tentacles", "--dry-run"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("no part", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reference_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "reference", "--help"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--part", result.stdout)
        self.assertIn("--dry-run", result.stdout)


if __name__ == "__main__":
    unittest.main()
