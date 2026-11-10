"""Stable-diffusion.cpp link/checkout contract tests without CUDA or inference."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
DOCTOR = ROOT / "doctor.sh"


def run(script, *args, root, env=None):
    settings = {**os.environ, "AI3D_ROOT": str(root)}
    settings.pop("SD_ROOT", None)
    settings.pop("SD_CLI", None)
    if env:
        settings.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=ROOT, env=settings, capture_output=True, text=True, timeout=15
    )


class SdCppDependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.root = self.path / "ai3d"
        self.root.mkdir()
        self.external = self.path / "external-sd"
        self.sd_bin = self.external / "build" / "bin"
        self.sd_bin.mkdir(parents=True)
        binary = self.sd_bin / "sd-cli"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        (self.external / "build" / "CMakeCache.txt").write_text("SD_CUDA:BOOL=ON\n")

    def test_existing_symlink_is_reused_without_modification(self):
        link = self.root / "stable-diffusion.cpp"
        link.symlink_to(self.external, target_is_directory=True)
        result = run(INSTALL, "--only", "sd-cpp", "--apply", root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[REUSE] stable-diffusion.cpp", result.stdout)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.external.resolve())

    def test_real_checkout_is_reused(self):
        link = self.root / "stable-diffusion.cpp"
        link.mkdir()
        (link / "build" / "bin").mkdir(parents=True)
        executable = link / "build" / "bin" / "sd-cli"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (link / "build" / "CMakeCache.txt").write_text("GGML_CUDA:BOOL=ON\n")
        result = run(INSTALL, "--only", "sd-cpp", "--dry-run", root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[REUSE]", result.stdout)

    def test_doctor_uses_same_symlink_path(self):
        link = self.root / "stable-diffusion.cpp"
        link.symlink_to(self.external, target_is_directory=True)
        result = run(DOCTOR, root=self.root)
        self.assertIn("[OK]      sd.cpp symlink", result.stdout)
        self.assertIn(str(link / "build/bin/sd-cli"), result.stdout)

    def test_broken_symlink_is_never_replaced(self):
        link = self.root / "stable-diffusion.cpp"
        link.symlink_to(self.path / "not_there", target_is_directory=True)
        for mode in ("--apply", "--dry-run"):
            with self.subTest(mode=mode):
                result = run(INSTALL, "--only", "sd-cpp", mode, root=self.root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Broken stable-diffusion.cpp symlink", result.stderr)
                self.assertTrue(link.is_symlink())

    def test_symlink_with_missing_binary_is_not_modified(self):
        link = self.root / "stable-diffusion.cpp"
        link.symlink_to(self.external, target_is_directory=True)
        (self.sd_bin / "sd-cli").unlink()
        result = run(INSTALL, "--only", "sd-cpp", "--apply", root=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to build through or replace it", result.stderr)
        self.assertTrue(link.is_symlink())

    def test_symlink_not_tracked_by_git(self):
        result = subprocess.run(
            ["git", "check-ignore", "stable-diffusion.cpp"],
            cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "stable-diffusion.cpp")


if __name__ == "__main__":
    unittest.main()
