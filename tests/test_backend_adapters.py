"""Pure backend adapter tests; no GPU, Blender or downloaded models needed."""

import ast
from pathlib import Path
import unittest

from ai3d.geometry.hunyuan import build_prepaint_command, build_shape_command
from ai3d.image.background import build_cutout_command
from ai3d.image.qwen import DEFAULT_SD_CLI, build_qwen_command
from ai3d.textures.paint3d import build_texture_command
from space_nova_pipeline.space_nova_pipeline import arguments


class BackendAdapterTests(unittest.TestCase):
    def test_qwen_default_is_project_local_and_symlink_compatible(self):
        self.assertEqual(DEFAULT_SD_CLI, Path(__file__).resolve().parents[1] / "stable-diffusion.cpp/build/bin/sd-cli")

    def test_pipeline_parser_default_matches_qwen_adapter(self):
        options = arguments(["--name", "test", "--stop-after", "shape"])
        self.assertEqual(options.sd_cli, DEFAULT_SD_CLI)

    def test_qwen_command_matches_legacy_arguments(self):
        command = build_qwen_command(Path("/sd-cli"), Path("/weights"),
                                     "a space captain", Path("/output.png"))
        self.assertEqual(command, [
            "systemd-run", "--user", "--scope", "-p", "MemoryMax=10G",
            "-p", "MemorySwapMax=1G", "/sd-cli",
            "--diffusion-model", "/weights/qwen-image-2512-Q3_K_M.gguf",
            "--llm", "/weights/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
            "--vae", "/weights/qwen_image_vae.safetensors",
            "--backend", "cuda0", "--params-backend", "disk", "--max-vram", "-1",
            "--diffusion-fa", "--cfg-scale", "2.5", "--sampling-method", "euler",
            "--flow-shift", "3", "--steps", "12", "-t", "4",
            "-W", "384", "-H", "576", "--seed", "42",
            "-p", "a space captain", "-o", "/output.png",
        ])

    def test_qwen_custom_limits_and_dimensions(self):
        command = build_qwen_command(
            Path("/cli"), Path("/qwen"), "ship", Path("/ship.png"),
            width=256, height=512, steps=8, ram_limit="8G", swap_limit="512M",
        )
        self.assertIn("MemoryMax=8G", command)
        self.assertIn("MemorySwapMax=512M", command)
        self.assertEqual(command[command.index("--steps") + 1], "8")
        self.assertEqual(command[command.index("-W") + 1], "256")

    def test_qwen_invalid_dimension(self):
        with self.assertRaises(ValueError):
            build_qwen_command(Path("/cli"), Path("/q"), "p", Path("/out"), width=0)

    def test_cli_accepts_backend_and_output_overrides(self):
        options = arguments([
            "--name", "test", "--sd-cli", "/custom/sd-cli",
            "--qwen-model-dir", "/custom/weights",
            "--output-dir", "/tmp/export",
        ])
        self.assertEqual(options.sd_cli, Path("/custom/sd-cli"))
        self.assertEqual(options.qwen_model_dir, Path("/custom/weights"))
        self.assertEqual(options.workdir, Path("/tmp/export"))

    def test_background_command_uses_hunyuan_environment(self):
        command = build_cutout_command(Path("/python"), Path("/ref.png"), Path("/out.png"))
        self.assertEqual(command[:2], ["/python", "-c"])
        ast.parse(command[2])
        self.assertEqual(command[3:], ["/ref.png", "/out.png", "auto"])
        bypass = build_cutout_command(Path("/python"), Path("/ref"), Path("/out"), skip=True)
        self.assertEqual(bypass[-1], "skip")

    def test_hunyuan_shape_cli(self):
        command = build_shape_command(
            Path("/hy-python"), Path("/first_mesh.py"),
            Path("/cutout.png"), Path("/shape.glb"),
        )
        self.assertEqual(command, [
            "/hy-python", "/first_mesh.py", "--input", "/cutout.png",
            "--output", "/shape.glb", "--steps", "20",
        ])

    def test_hunyuan_prepaint_cli(self):
        command = build_prepaint_command(
            "blender", Path("/optimize_mesh.py"),
            Path("/shape.glb"), Path("/paint_mesh.glb"),
        )
        self.assertEqual(command, [
            "blender", "--background", "--factory-startup",
            "--python-exit-code", "1", "--python", "/optimize_mesh.py",
            "--", "--input", "/shape.glb", "--target-faces", "40000",
            "--output", "/paint_mesh.glb",
        ])

    def test_paint3d_cli_preserves_legacy_arguments(self):
        command = build_texture_command(
            Path("/paint-python"), Path("/mesh.glb"),
            Path("/image.png"), Path("/painted.glb"),
        )
        self.assertEqual(command, [
            "/paint-python", "-m", "paint3d", "texture", "/mesh.glb",
            "-i", "/image.png", "-o", "/painted.glb", "--quality", "fast",
            "--max-views", "2", "--view-resolution", "256",
            "--render-size", "512", "--texture-size", "1024",
            "--bake-exp", "6", "--no-vramd", "--profile",
            "--category", "humanoid",
        ])

    def test_paint3d_none_category_omits_flag(self):
        command = build_texture_command(
            Path("/p"), Path("/m"), Path("/i"), Path("/o"),
            category="none", quality="low",
        )
        self.assertNotIn("--category", command)
        self.assertIn("low", command)

    def test_paint3d_rejects_bad_quality(self):
        with self.assertRaises(ValueError):
            build_texture_command(
                Path("/p"), Path("/m"), Path("/i"), Path("/o"),
                quality="unsupported",
            )


if __name__ == "__main__":
    unittest.main()
