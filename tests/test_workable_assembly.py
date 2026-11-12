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
    use_prior_approved_head, write_assembly_gallery,
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

    def make_dummy_sources(self):
        paths = sources(self.card, self.name, self.root)
        for source in paths.values():
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"unaltered-generated-glb")
        return paths

    def test_gallery_contains_six_parts_and_four_combined_views(self):
        folder = self.root / "mara_assembled_six"
        folder.mkdir(parents=True)
        for filename in ("preview.blend", "preview.glb", "assembly.json",
                         "measurements.json"):
            (folder / filename).write_bytes(b"sample")
        for direction in ("front", "side", "back", "threequarter"):
            (folder / f"preview_{direction}.png").write_bytes(b"sample-png")
        index = write_assembly_gallery(
            folder, self.card, sources(self.card, self.name, self.root)
        )
        html = index.read_text(encoding="utf-8")
        self.assertEqual(html.count("<figure>"), 4)
        self.assertEqual(html.count("<li>"), 6)
        self.assertIn("Head, face and hairstyle", html)
        self.assertNotIn("Hair / head covering", html)
        self.assertNotIn("_hair_hair_closeup", html)
        self.assertIn("preview.blend", html)
        self.assertIn("preview.glb", html)
        self.assertIn("assembly.json", html)

        index.unlink()
        (folder / "preview_side.png").unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing assembled render"):
            write_assembly_gallery(
                folder, self.card, sources(self.card, self.name, self.root)
            )

    def test_existing_seven_part_manifest_is_never_rebuilt(self):
        self.make_dummy_sources()
        folder = self.root / (self.name + "_workable_character")
        folder.mkdir()
        manifest = {
            "character_id": self.card["id"], "run_prefix": self.name,
            "parts": [{"id": part["id"]} for part in self.card["parts"]]
                     + [{"id": "hair"}],
        }
        original = json.dumps(manifest).encode()
        file = folder / "assembly.json"
        file.write_bytes(original)
        with patch("ai3d.characters.workable_assembly.assemble_preview") as builder:
            with patch("ai3d.characters.workable_assembly.shutil.which",
                       return_value="/usr/bin/blender"):
                with self.assertRaisesRegex(RuntimeError, "Part inventory changed"):
                    assemble(self.options())
            builder.assert_not_called()
        self.assertEqual(file.read_bytes(), original)
        self.assertFalse((folder / "preview.blend").exists())

    def test_six_part_end_to_end_assembly_and_gallery_without_ai_models(self):
        inputs = self.make_dummy_sources()
        target = self.name + "_assembled_v1"
        source_contents = {ident: path.read_bytes() for ident, path in inputs.items()}
        sizes = {
            "body": ((-.3, -.2, 0.0), (.3, .2, 1.7)),
            "head": ((-.12, -.12, 0.0), (.12, .12, .32)),
            "upper_outfit": ((-.23, -.15, 0.0), (.23, .15, .63)),
            "lower_outfit": ((-.22, -.15, 0.0), (.22, .15, .9)),
            "hands": ((-.42, -.10, 0.0), (.42, .10, .2)),
            "equipment": ((-.2, -.12, 0.0), (.2, .12, .2)),
        }

        def fake_blender_build(_card_path, *, name, run_prefix,
                               output_root, rebuild=False, **_kwargs):
            folder = Path(output_root) / name
            folder.mkdir(parents=True, exist_ok=True)
            manifest_file = folder / "assembly.json"
            if not rebuild:
                plan = build_assembly_plan(
                    self.card, run_prefix=run_prefix, name=name,
                    output_root=output_root, layout="overlay",
                    include_all_parts=True,
                )
                manifest_file.write_text(json.dumps(plan))
            manifest = json.loads(manifest_file.read_text())
            report = {
                "character_id": self.card["id"],
                "components": [
                    {"id": item["id"], "bounds_with_user_transform": {
                        "min": list(sizes[item["id"]][0]),
                        "max": list(sizes[item["id"]][1]),
                    }}
                    for item in manifest["parts"]
                ],
            }
            (folder / "measurements.json").write_text(json.dumps(report))
            (folder / "preview.blend").write_bytes(b"mock-blend")
            (folder / "preview.glb").write_bytes(b"mock-combined-glb")

        def fake_render(_blender, folder):
            for direction in ("front", "side", "back", "threequarter"):
                (folder / f"preview_{direction}.png").write_bytes(b"fake-image")

        with patch("ai3d.characters.workable_assembly.assemble_preview",
                   side_effect=fake_blender_build) as preview:
            with patch("ai3d.characters.workable_assembly.render_scene",
                       side_effect=fake_render):
                with patch("ai3d.characters.workable_assembly.shutil.which",
                           return_value="/usr/bin/blender"):
                    folder = assemble(self.options("--name", target))
                    self.assertEqual(preview.call_count, 2)

                    manifest_file = folder / "assembly.json"
                    manifest = json.loads(manifest_file.read_text())
                    self.assertEqual([part["id"] for part in manifest["parts"]],
                                     list(inputs))
                    self.assertEqual(len(manifest["parts"]), 6)
                    self.assertTrue(all(
                        p["visible"] and p["include_in_preview"]
                        for p in manifest["parts"]
                    ))
                    self.assertEqual(manifest["parts"][0]["cut"]["mode"], "apply")
                    self.assertEqual(manifest["parts"][1]["cut"]["mode"], "apply")
                    self.assertEqual(manifest["auto_fit"]["version"], 3)
                    upper = next(p for p in manifest["parts"]
                                 if p["id"] == "upper_outfit")
                    trousers = next(p for p in manifest["parts"]
                                    if p["id"] == "lower_outfit")
                    hands = next(p for p in manifest["parts"] if p["id"] == "hands")
                    self.assertEqual(upper["status"], "landmark_box_fit_unverified")
                    self.assertEqual(trousers["status"], "landmark_box_fit_unverified")
                    self.assertEqual(hands["status"], "glove_pair_split_planned")
                    self.assertEqual(hands["pair_layout"]["mode"],
                                     "split_x_to_wrists_v1")
                    self.assertTrue((folder / "index.html").is_file())
                    self.assertNotIn("_hair_", (folder / "index.html").read_text())
                    self.assertEqual({ident: path.read_bytes() for ident, path
                                      in inputs.items()}, source_contents)

                    # A second run must preserve intentional manual placement.
                    manifest["parts"][2]["transform"]["position"][0] = 0.1234
                    manifest_file.write_text(json.dumps(manifest))
                    assemble(self.options("--name", target))
                    preserved = json.loads(manifest_file.read_text())
                    self.assertEqual(
                        preserved["parts"][2]["transform"]["position"][0], 0.1234
                    )

    def test_named_output_is_separate_and_protected(self):
        self.assertEqual(self.options("--name", "mara_six_assembled").name,
                         "mara_six_assembled")
        with self.assertRaises(SystemExit):
            self.options("--name", "../escape")
        options = self.options("--name", self.name + "_assembly", "--dry-run")
        with self.assertRaisesRegex(RuntimeError, "reserved for existing assets"):
            assemble(options)

    def test_cli_dry_run_and_error_path(self):
        cmd = ["bash", str(ROOT / "build_character.sh"), "--assemble-workable",
               "--output-dir", str(self.root), "--prefix", self.name]
        result = subprocess.run(cmd + ["--dry-run"], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WORKABLE ASSEMBLY", result.stdout)
        self.assertIn("6 independent parts", result.stdout)
        self.assertFalse(self.root.exists())
        named = subprocess.run(cmd + ["--assembly", "mara_assembled_six",
                                      "--dry-run"], cwd=ROOT,
                               capture_output=True, text=True)
        self.assertEqual(named.returncode, 0, named.stdout + named.stderr)
        self.assertIn("mara_assembled_six", named.stdout)
        self.assertFalse(self.root.exists())
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing painted GLB", result.stderr)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
