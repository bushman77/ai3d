"""Offline tests for non-destructive Blender character assembly preview."""

import ast
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

from ai3d.characters.assembly import (
    SCRIPT, assemble_preview, build_assembly_plan,
    build_blender_command, validate_manifest,
)
from ai3d.characters.card import ROOT, load_card
from ai3d.pipeline_runner import Runner

MARA = ROOT / "examples/space_nova/characters/mara_venn.json"


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "outputs"
        self.card = load_card(MARA)
        self.blender = Path(self.tmp.name) / "blender"
        self.blender.write_text("#!/bin/sh\nexit 0\n")
        self.blender.chmod(0o755)
        self.options = dict(
            name="mara_assembly_v1", run_prefix="mara_components_v1",
            output_root=self.root, blender=str(self.blender),
        )

    def plan(self, **kwargs):
        return build_assembly_plan(
            self.card, **{
                **{
                    "run_prefix": "mara_components_v1",
                    "name": "mara_assembly_v1",
                    "output_root": self.root,
                }, **kwargs,
            },
        )

    def create_inputs(self, manifest=None):
        manifest = manifest or self.plan()
        for part in manifest["parts"]:
            source = Path(part["source"])
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"fake-glb:" + part["id"].encode())
        return manifest

    def fake_blender(self, runner, label, command, cwd=None, env=None):
        self.assertEqual(label, "assembly-preview")
        self.assertIn("--python-exit-code", command)
        self.assertIn("--manifest", command)
        manifest_path = Path(command[-1])
        data = json.loads(manifest_path.read_text())
        for key in ("blend", "glb", "measurements"):
            Path(data["output"][key]).write_bytes(b"test-artifact-" + key.encode())

    def create_preview(self, *, manifest=None):
        self.create_inputs(manifest)
        with patch("ai3d.characters.assembly.readable_glb") as valid:
            with patch.object(Runner, "command", autospec=True, side_effect=self.fake_blender):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = assemble_preview(MARA, **self.options)
        self.assertEqual(valid.call_count, 2)
        return result

    def test_plan_uses_high_resolution_original_painted_sources(self):
        data = self.plan()
        self.assertEqual(data["source_stage"], "painted")
        self.assertEqual(data["base_part"], "body")
        self.assertEqual(data["preview_layout"], "side_by_side")
        self.assertEqual([p["id"] for p in data["parts"]], ["body", "head"])
        self.assertEqual(
            Path(data["parts"][0]["source"]).name, "05_painted.glb"
        )
        self.assertIn("mara_components_v1_head_head_closeup", data["parts"][1]["source"])
        self.assertEqual(data["parts"][1]["status"], "unfitted")

    def test_plan_can_choose_game_stage(self):
        data = self.plan(source_stage="game")
        self.assertEqual(Path(data["parts"][0]["source"]).name, "06_game.glb")

    def test_plan_supports_other_character_part_ids(self):
        data = self.plan(base="body", attach="equipment")
        self.assertEqual([p["id"] for p in data["parts"]], ["body", "equipment"])

    def test_invalid_inputs_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "distinct"):
            self.plan(base="body", attach="body")
        with self.assertRaisesRegex(RuntimeError, "Unknown part"):
            self.plan(attach="not_real")
        with self.assertRaisesRegex(RuntimeError, "name must contain"):
            self.plan(name="../escape")

    def test_preview_manifest_has_editable_transform_contract(self):
        data = self.plan()
        self.assertEqual(validate_manifest(data, self.root / "mara_assembly_v1"), [])
        for component in data["parts"]:
            self.assertEqual(component["transform"]["position"], [0.0, 0.0, 0.0])
            self.assertEqual(component["transform"]["scale"], [1.0, 1.0, 1.0])

    def test_dry_run_is_read_only_even_if_sources_are_missing(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            data = assemble_preview(MARA, dry_run=True, **self.options)
        self.assertEqual(data["character_id"], "mara_venn")
        self.assertIn("MISSING", output.getvalue())
        self.assertFalse(self.root.exists())

    def test_missing_source_prevents_manifest_write(self):
        with self.assertRaisesRegex(RuntimeError, "Missing or empty source GLB"):
            assemble_preview(MARA, **self.options)
        self.assertFalse(self.root.exists())

    def test_output_does_not_modify_source_glbs(self):
        manifest = self.plan()
        self.create_preview(manifest=manifest)
        for component in manifest["parts"]:
            source = Path(component["source"])
            self.assertEqual(source.read_bytes(), b"fake-glb:" + component["id"].encode())

    def test_preview_outputs_are_self_contained(self):
        result = self.create_preview()
        folder = self.root / "mara_assembly_v1"
        self.assertTrue((folder / "assembly.json").is_file())
        self.assertTrue((folder / "preview.blend").is_file())
        self.assertTrue((folder / "preview.glb").is_file())
        self.assertTrue((folder / "measurements.json").is_file())
        self.assertTrue((folder / "logs").is_dir())
        self.assertEqual(json.loads((folder / "assembly.json").read_text()), result)
        self.assertIn("source_sha256", result)
        self.assertEqual(len(result["source_sha256"]), 2)

    def test_source_validation_happens_before_blender_launch(self):
        self.create_inputs()
        with patch("ai3d.characters.assembly.readable_glb", side_effect=RuntimeError("bad GLB")):
            with patch.object(Runner, "command") as mocked:
                with self.assertRaisesRegex(RuntimeError, "bad GLB"):
                    assemble_preview(MARA, **self.options)
                mocked.assert_not_called()
        self.assertFalse((self.root / "mara_assembly_v1").exists())

    def test_existing_output_requires_explicit_rebuild(self):
        self.create_preview()
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            assemble_preview(MARA, **self.options)

    def test_rebuild_preserves_manifest_edits(self):
        self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        data = json.loads(path.read_text())
        data["preview_layout"] = "overlay"
        data["parts"][1]["transform"]["position"] = [1.0, 2.0, 3.0]
        data["parts"][1]["transform"]["rotation_deg"] = [0.0, 0.0, 90.0]
        path.write_text(json.dumps(data))
        with patch("ai3d.characters.assembly.readable_glb"):
            with patch.object(Runner, "command", autospec=True, side_effect=self.fake_blender):
                assemble_preview(MARA, rebuild=True, **self.options)
        restored = json.loads(path.read_text())
        self.assertEqual(restored["preview_layout"], "overlay")
        self.assertEqual(restored["parts"][1]["transform"]["position"], [1.0, 2.0, 3.0])

    def test_rebuild_requires_existing_manifest(self):
        with self.assertRaisesRegex(RuntimeError, "requires an existing"):
            assemble_preview(MARA, rebuild=True, **self.options)

    def test_reject_invalid_negative_scale(self):
        data = self.plan()
        data["parts"][1]["transform"]["scale"][0] = -1
        result = validate_manifest(data, self.root / "mara_assembly_v1")
        self.assertTrue(any("scale" in line for line in result))

    def test_reject_nonfinite_transform(self):
        data = self.plan()
        data["parts"][1]["transform"]["position"][0] = float("inf")
        self.assertTrue(any("position" in e for e in validate_manifest(data, self.root / "mara_assembly_v1")))

    def test_reject_outputs_outside_assembly_folder(self):
        data = self.plan()
        data["output"]["blend"] = str(Path(self.tmp.name) / "other.blend")
        self.assertTrue(any("output.blend" in e for e in validate_manifest(data, self.root / "mara_assembly_v1")))

    def test_reject_symlinked_run_folder(self):
        external = Path(self.tmp.name) / "external"
        external.mkdir()
        self.root.mkdir()
        (self.root / "mara_assembly_v1").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            assemble_preview(MARA, dry_run=True, **self.options)
        self.assertEqual(list(external.iterdir()), [])

    def test_command_uses_safe_argument_vector(self):
        command = build_blender_command(
            "blender", Path("/path/script.py"), Path("/path/manifest.json")
        )
        self.assertEqual(command, [
            "blender", "--background", "--factory-startup",
            "--python-exit-code", "1", "--python", "/path/script.py",
            "--", "--manifest", "/path/manifest.json",
        ])

    def test_blender_script_is_syntactically_valid(self):
        ast.parse(SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("bpy.ops.import_scene.gltf", SCRIPT.read_text())
        self.assertNotIn("bpy.ops.object.join(", SCRIPT.read_text())

    def test_cli_help_displays_assembly_options(self):
        r = subprocess.run(
            [sys.executable, "-m", "ai3d", "character", "assemble", "--help"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        for key in ("--run-prefix", "--name", "--base", "--attach", "--rebuild", "--dry-run"):
            self.assertIn(key, r.stdout)

    def test_cli_dry_run_without_sources(self):
        r = subprocess.run(
            [
                sys.executable, "-m", "ai3d", "character", "assemble", str(MARA),
                "--run-prefix", "mara_components_v1",
                "--name", "mara_assembly_v1",
                "--output-dir", str(self.root), "--dry-run",
            ],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mara_components_v1_head_head_closeup", r.stdout)
        self.assertFalse(self.root.exists())


    def test_new_assembly_has_disabled_cut_config_for_each_part(self):
        data = self.plan()
        self.assertEqual(data["parts"][0]["cut"]["mode"], "off")
        self.assertEqual(data["parts"][0]["cut"]["keep"], "below")
        self.assertEqual(data["parts"][1]["cut"]["keep"], "above")
        self.assertEqual(validate_manifest(data, self.root / "mara_assembly_v1"), [])

    def test_old_v1_manifest_without_cut_fields_still_valid(self):
        data = self.plan()
        for part in data["parts"]:
            part.pop("cut")
        self.assertEqual(validate_manifest(data, self.root / "mara_assembly_v1"), [])

    def test_guide_and_apply_are_valid_only_with_numeric_finite_z(self):
        data = self.plan()
        cut = data["parts"][0]["cut"]
        cut.update(mode="guide", plane_z=0.75)
        self.assertEqual(validate_manifest(data, self.root / "mara_assembly_v1"), [])
        cut.update(mode="apply", plane_z=0.75)
        self.assertEqual(validate_manifest(data, self.root / "mara_assembly_v1"), [])
        for value in (float("nan"), float("inf"), "0.75", None, True):
            with self.subTest(z=value):
                cut["plane_z"] = value
                self.assertTrue(any("plane_z" in err for err in validate_manifest(
                    data, self.root / "mara_assembly_v1"
                )))
        cut["plane_z"] = 0.75
        cut["mode"] = "delete_everything"
        self.assertTrue(any(".mode" in err for err in validate_manifest(
            data, self.root / "mara_assembly_v1"
        )))

    def test_bad_keep_side_and_guide_toggle_rejected(self):
        data = self.plan()
        cut = data["parts"][0]["cut"]
        cut["keep"] = "all"
        self.assertTrue(any(".keep" in err for err in validate_manifest(
            data, self.root / "mara_assembly_v1"
        )))
        cut["keep"] = "below"
        cut["show_guide"] = "no"
        self.assertTrue(any("show_guide" in err for err in validate_manifest(
            data, self.root / "mara_assembly_v1"
        )))

    def test_configure_cut_requires_explicit_z_for_guide_apply(self):
        from ai3d.characters.assembly import configure_cut
        self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        original = path.read_bytes()
        for mode in ("guide", "apply"):
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, "explicit --z"):
                configure_cut(path, part_id="body", mode=mode)
            self.assertEqual(original, path.read_bytes())

    def test_guide_preview_does_not_touch_source_or_assembly_manifest(self):
        from ai3d.characters.assembly import configure_cut
        data = self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        before = path.read_bytes()
        configure_cut(path, part_id="body", mode="guide", plane_z=0.76, dry_run=True)
        self.assertEqual(before, path.read_bytes())
        for part in data["parts"]:
            self.assertEqual(Path(part["source"]).read_bytes(),
                             b"fake-glb:" + part["id"].encode())

    def test_update_cut_then_rebuild_keeps_unchanged_source_models(self):
        from ai3d.characters.assembly import configure_cut
        data = self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        configure_cut(path, part_id="body", mode="guide", plane_z=0.76)
        configure_cut(path, part_id="head", mode="guide", plane_z=0.68)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["parts"][0]["cut"]["mode"], "guide")
        self.assertEqual(saved["parts"][1]["cut"]["plane_z"], 0.68)
        with patch("ai3d.characters.assembly.readable_glb"):
            with patch.object(Runner, "command", autospec=True, side_effect=self.fake_blender):
                assemble_preview(MARA, rebuild=True, **self.options)
        for part in data["parts"]:
            self.assertEqual(Path(part["source"]).read_bytes(),
                             b"fake-glb:" + part["id"].encode())

    def test_apply_can_revert_to_off_by_editing_manifest(self):
        from ai3d.characters.assembly import configure_cut
        self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        configure_cut(path, part_id="body", mode="apply", plane_z=0.75)
        assert json.loads(path.read_text())["parts"][0]["cut"]["mode"] == "apply"
        configure_cut(path, part_id="body", mode="off")
        saved = json.loads(path.read_text())
        self.assertEqual(saved["parts"][0]["cut"]["mode"], "off")
        self.assertEqual(saved["parts"][0]["cut"]["plane_z"], 0.75)

    def test_old_manifest_is_automatically_extended_when_cut_is_configured(self):
        from ai3d.characters.assembly import configure_cut
        self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        data = json.loads(path.read_text())
        data["parts"][0].pop("cut")
        path.write_text(json.dumps(data))
        configure_cut(path, part_id="body", mode="guide", plane_z=0.75)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["parts"][0]["cut"]["keep"], "below")

    def test_cut_command_cli_supports_dry_run_and_validation(self):
        self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        unchanged = path.read_bytes()
        cmd = [
            sys.executable, "-m", "ai3d", "character", "cut",
            str(path), "--part", "body", "--mode", "guide", "--z", "0.75",
        ]
        preview = subprocess.run(
            [*cmd, "--dry-run"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(unchanged, path.read_bytes())
        applied = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["parts"][0]["cut"]["mode"], "guide")
        self.assertEqual(saved["parts"][0]["cut"]["plane_z"], 0.75)

    def test_cut_cli_rejects_apply_without_z(self):
        self.create_preview()
        path = self.root / "mara_assembly_v1/assembly.json"
        cmd = [
            sys.executable, "-m", "ai3d", "character", "cut",
            str(path), "--part", "body", "--mode", "apply",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("explicit --z", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_blender_cut_helpers_are_syntactically_valid_and_copy_meshes(self):
        helper = ROOT / "ai3d/assembly/blender_cutting.py"
        script = SCRIPT.read_text(encoding="utf-8")
        cut_code = helper.read_text(encoding="utf-8")
        ast.parse(cut_code)
        ast.parse(script)
        self.assertIn("mesh = obj.data.copy()", cut_code)
        self.assertIn("bmesh.ops.bisect_plane(", cut_code)
        self.assertIn("scene_root.children.unlink(guides)", script)
        self.assertNotIn("bpy.ops.object.join(", script)


if __name__ == "__main__":
    unittest.main()
