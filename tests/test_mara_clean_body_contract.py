"""Regression checks for the staged clean-body restart (no GPU or Blender)."""
from pathlib import Path
import unittest

from ai3d.characters.card import load_card
from ai3d.characters.reference import compose_reference_prompt, select_part_and_view


CARD = Path(__file__).resolve().parents[1] / "examples/space_nova/characters/mara_venn.json"


class MaraCleanBodyContractTest(unittest.TestCase):
    def test_body_reference_has_clean_jumpsuit_without_gear(self):
        card = load_card(CARD)
        body, view = select_part_and_view(card, "body")
        positive = body["prompts"]["reference"].lower()
        for disallowed in ("belt", "pouch", "holster", "repair tool", "thigh rig"):
            self.assertNotIn(disallowed, positive, f"positive body prompt includes {disallowed!r}")
        self.assertIn("jumpsuit", positive)
        self.assertIn("uninterrupted", positive)
        self.assertIn("a-pose", positive)
        self.assertEqual(view, "front")
        combined = compose_reference_prompt(card, body, view).lower()
        self.assertIn("no utility belt", combined)
        self.assertIn("no missing fabric", combined)
        self.assertIn("single-character studio reference", combined)
        self.assertIn("adult human", positive)

    def test_design_brief_still_preserves_full_equipment_identity(self):
        card = load_card(CARD)
        self.assertIn("utility belt", card["prompts"]["master"].lower())
        self.assertTrue(any(p["id"] == "equipment" for p in card["parts"]))
        self.assertGreaterEqual(card["revision"], 3)


if __name__ == "__main__":
    unittest.main()
