"""Behavioral regression tests for the original stage runner extraction."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

from ai3d.pipeline_runner import Runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.txt"
        self.source.write_text("first")
        self.dest = self.root / "run" / "output.txt"

    def stage(self, runner):
        runner.run("copy", [self.source], [self.dest], {"type": "copy"},
                   lambda: runner.copy(self.source, self.dest))

    def test_stage_outputs_and_manifest(self):
        runner = Runner(self.dest.parent, resume=False, force=False, dry=False)
        self.stage(runner)
        self.assertEqual(self.dest.read_text(), "first")
        self.assertTrue((runner.meta / "copy.json").exists())
        self.assertFalse(runner.timing["copy"]["cached"])

    def test_resume_and_changed_input(self):
        first = Runner(self.dest.parent, resume=False, force=False, dry=False)
        self.stage(first)
        second = Runner(self.dest.parent, resume=True, force=False, dry=False)
        self.stage(second)
        self.assertTrue(second.timing["copy"]["cached"])
        self.source.write_text("second version")
        third = Runner(self.dest.parent, resume=True, force=False, dry=False)
        self.stage(third)
        self.assertFalse(third.timing["copy"]["cached"])
        self.assertEqual(self.dest.read_text(), "second version")

    def test_force_overrides_cache(self):
        first = Runner(self.dest.parent, resume=False, force=False, dry=False)
        self.stage(first)
        second = Runner(self.dest.parent, resume=True, force=True, dry=False)
        self.stage(second)
        self.assertFalse(second.timing["copy"]["cached"])

    def test_dry_run_does_not_create_output_or_invoke_callback(self):
        called = []
        runner = Runner(self.dest.parent, resume=False, force=False, dry=True)
        runner.run("copy", [self.source], [self.dest], {}, lambda: called.append(True))
        self.assertFalse(called)
        self.assertFalse(self.dest.parent.exists())

    def test_command_captures_subprocess_output(self):
        runner = Runner(self.dest.parent, resume=False, force=False, dry=False)
        cmd = [sys.executable, "-c", "print('runner okay')"]
        with redirect_stdout(StringIO()):
            runner.command("hello", cmd)
        self.assertIn("runner okay", (runner.logs / "hello.log").read_text())

    def test_failing_command_reports_error(self):
        runner = Runner(self.dest.parent, resume=False, force=False, dry=False)
        cmd = [sys.executable, "-c", "raise SystemExit(7)"]
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "exit 7"):
            runner.command("broken", cmd)


if __name__ == "__main__":
    unittest.main()
