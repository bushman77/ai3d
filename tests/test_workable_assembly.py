"""Offline tests for the non-destructive all-component assembly coordinator."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai3d.characters.card import ROOT, load_card
from ai3d.characters.assembly import build_assembly_plan
from ai3d.characters.workable_assembly import (
    args_from_cli, assemble, enable_workable_parts, sources,
    use_prior_approved_head,
)

CARD = ROOT / "examples/space_nova/characters/mara_venn.json"


class WorkableAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "outputs"
        self.card = load_card(CARD)
        self.name = "mara_workable_test"

    def options(self, *extra):
        return args_from_cli([
            "--card", str(CARD), "--prefix", self.name,
            "--output-dir", str(self.root), *extra,
        ])

    def test_dry_run_is_non_mutating_and_includes_all_six_glbs(self):
        out = assemble(self.options("--dry-run"))
        self.assertFalse(out.exists())
        self.assertFalse(self.root.exists())
        expected = sources(self.card, self.name, self.root)
        self.assertEqual(list(expected), [p["id"] for p in self.card["parts"]])
        self.assertEqual(len(expected), 6)
        self.assertTrue(all(p.name == "05_painted.glb" for p in expected.values()))

    def test_missing_source_fails_before_writing_anything(self):
        with self.assertRaisesRegex(RuntimeError, "Missing painted GLB"):
            assemble(self.options())
        self.assertFalse(self.root.exists())

    def test_workable_enables_all_parts_without_erasing_cut_or_transform(self):
        plan = build_assembly_plan(
            self.card, run_prefix=self.name, name=self.name + "_workable_character",
            output_root=self.root, include_all_parts=True,
        )
        before = deepcopy(plan["parts"][:2])
        enable_workable_parts(plan)
        self.assertEqual(plan["workable_version"], 1)
        self.assertEqual(plan["preview_layout"], "overlay")
        self.assertEqual(len(plan["parts"]), 6)
        self.assertTrue(all(p["visible"] and p["include_in_preview"]
                            for p in plan["parts"]))
        self.assertEqual(plan["parts"][0]["transform"], before[0]["transform"])
        self.assertEqual(plan["parts"][1]["cut"], before[1]["cut"])

    def test_prior_assembly_preserves_body_and_head_only_from_matching_sources(self):
        plan = build_assembly_plan(
            self.card, run_prefix=self.name, name=self.name + "_workable_character",
            output_root=self.root, include_all_parts=True,
        )
        old = deepcopy(plan)
        old["parts"] = old["parts"][:2]
        old["parts"][0]["cut"] = {"mode": "apply", "keep": "below",
                                  "plane_z": 0.68, "show_guide": False}
        old["parts"][1]["cut"] = {"mode": "apply", "keep": "above",
                                  "plane_z": 0.68, "show_guide": False}
        old["parts"][1]["transform"]["position"] = [0.01, -0.03, 0.75]
        previous = Path(self.tmp.name) / "existing.json"
        previous.write_text(json.dumps(old))
        self.assertTrue(use_prior_approved_head(plan, previous))
        self.assertEqual(plan["parts"][1]["transform"]["position"],
                         [0.01, -0.03, 0.75])
        self.assertEqual(plan["parts"][0]["cut"]["plane_z"], 0.68)
        self.assertEqual(plan["parts"][2]["id"], "upper_outfit")

        changed = deepcopy(plan)
        changed["parts"][1]["source"] = str(self.root / "other.glb")
        self.assertFalse(use_prior_approved_head(changed, previous))
        self.assertEqual(changed["parts"][1]["transform"]["position"],
                         [0.01, -0.03, 0.75])

    def test_cli_dry_run_and_error_path(self):
        cmd = ["bash", str(ROOT / "build_character.sh"), "--assemble-workable",
               "--output-dir", str(self.root), "--prefix", self.name]
        result = subprocess.run(cmd + ["--dry-run"], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WORKABLE ASSEMBLY", result.stdout)
        self.assertIn("6 independent parts", result.stdout)
        self.assertFalse(self.root.exists())
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing painted GLB", result.stderr)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
