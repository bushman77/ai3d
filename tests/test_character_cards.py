"""Project-independent, permanent character-card contract tests (no AI dependencies)."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ai3d.characters.card import (
    ROOT, TEMPLATE_PATH, DEFAULT_CARDS_DIR,
    load_card, new_card, save_new_card, validate_card,
)


class CharacterCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_shipped_template_is_valid_and_has_key_components(self):
        template = json.loads(TEMPLATE_PATH.read_text())
        self.assertEqual([], validate_card(template))
        ids = {part["id"] for part in template["parts"]}
        self.assertTrue({"head", "body", "hair", "outfit", "hands", "equipment"} <= ids)
        self.assertEqual(template["schema_version"], 1)

    def test_new_card_has_independent_parts_and_name(self):
        first = new_card("captain_lira", "Captain Lira", "android")
        second = new_card("new_character")
        first["parts"][0]["prompts"]["geometry"] = "changed"
        self.assertEqual(second["parts"][0]["prompts"]["geometry"], "")
        self.assertEqual(first["name"], "Captain Lira")
        self.assertEqual(second["name"], "New Character")
        self.assertEqual(first["category"], "android")

    def test_default_card_root_is_repository_source_not_outputs(self):
        self.assertEqual(DEFAULT_CARDS_DIR, ROOT / "characters")
        self.assertNotIn("outputs", DEFAULT_CARDS_DIR.parts)

    def test_save_reload_and_refuse_overwrite(self):
        destination = self.folder / "characters" / "captain_lira.json"
        card = new_card("captain_lira")
        save_new_card(card, destination)
        self.assertEqual(load_card(destination), card)
        with self.assertRaises(FileExistsError):
            save_new_card(new_card("captain_lira", "Changed"), destination)
        self.assertEqual(load_card(destination)["name"], "Captain Lira")

    def test_invalid_id_rejected(self):
        for identifier in ("../escape", "bad/name", "UPPERCASE", "", "x.."):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                new_card(identifier)

    def test_wrong_schema_version_rejected(self):
        card = new_card("test")
        card["schema_version"] = 2
        self.assertIn("schema_version must be 1", validate_card(card))

    def test_missing_parts_rejected(self):
        card = new_card("test")
        card["parts"] = []
        self.assertTrue(any("parts must be" in e for e in validate_card(card)))

    def test_duplicate_parts_rejected(self):
        card = new_card("test")
        card["parts"].append(deepcopy(card["parts"][0]))
        self.assertTrue(any("duplicate part" in e for e in validate_card(card)))

    def test_invalid_parent_and_cycles_rejected(self):
        card = new_card("test")
        card["parts"][1]["parent"] = "missing"
        self.assertTrue(any("unknown parent" in e for e in validate_card(card)))
        card["parts"][1]["parent"] = "body"
        card["parts"][0]["parent"] = "head"
        self.assertTrue(any("cycle" in e for e in validate_card(card)))

    def test_reference_ids_checked(self):
        card = new_card("test")
        card["parts"][1]["reference_ids"] = ["head_front"]
        self.assertTrue(any("unknown reference" in e for e in validate_card(card)))
        card["references"].append({
            "id": "head_front",
            "path": "images/head_front.png",
            "purpose": "head geometry",
            "view": "front",
        })
        self.assertEqual(validate_card(card), [])

    def test_invalid_card_refuses_to_write(self):
        card = new_card("test")
        card["parts"] = []
        destination = self.folder / "nonexistent" / "test.json"
        with self.assertRaises(RuntimeError):
            save_new_card(card, destination)
        self.assertFalse(destination.parent.exists())

    def test_wrong_generation_settings_rejected(self):
        card = new_card("test")
        card["parts"][1]["generation"]["view_resolution"] = -32
        self.assertTrue(any("view_resolution" in e for e in validate_card(card)))

    def test_schema_is_valid_json_schema_manifest(self):
        schema = json.loads((TEMPLATE_PATH.parent / "schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertIn("parts", schema["required"])

    def test_worked_mara_example_is_valid(self):
        path = ROOT / "examples/space_nova/characters/mara_venn.json"
        card = load_card(path)
        self.assertEqual(card["id"], "mara_venn")
        self.assertIn("head", [part["id"] for part in card["parts"]])
        self.assertIn("spaceport", card["prompts"]["master"].lower())

    def test_rejects_unhashable_kind_gracefully(self):
        card = new_card("test")
        card["parts"][0]["kind"] = []
        self.assertTrue(any("kind" in e for e in validate_card(card)))

    def test_cli_reports_invalid_id_without_traceback(self):
        result = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "init", "../escape"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("snake_case", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_init_then_validate(self):
        destination = self.folder / "new_character.json"
        init = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "init", "new_character",
             "--name", "New Character", "--output", str(destination)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        validate = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "validate", str(destination)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(validate.returncode, 0, validate.stderr)
        self.assertIn("VALID: new_character", validate.stdout)
        self.assertIn("head", validate.stdout)

    def test_cli_refuses_overwrite(self):
        destination = self.folder / "existing.json"
        args = [
            sys.executable, "-m", "ai3d", "character", "init", "new_character",
            "--output", str(destination),
        ]
        first = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        second = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 1)
        self.assertIn("refusing overwrite", second.stderr)

    def test_cli_help_describes_cards(self):
        r = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "--help"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("init", r.stdout)
        self.assertIn("validate", r.stdout)


if __name__ == "__main__":
    unittest.main()
