"""ai3d make: the guided procedure, driven with a fake pipeline (no GPU)."""
import json
from pathlib import Path
import tempfile
import unittest

from ai3d.make import Maker, arguments


class FakePipeline:
    """Records calls; writes the files the real pipeline would."""

    def __init__(self, home: Path, fail_with=None):
        self.home = home
        self.calls = []
        self.fail_with = list(fail_with or [])  # [(stage, log text), ...] for full runs

    def __call__(self, argv):
        self.calls.append(argv)
        self.home.mkdir(parents=True, exist_ok=True)
        if "--stop-after" in argv:
            for angle in ("left", "back", "right"):
                (self.home / f"01_view_{angle}.png").write_bytes(b"png")
            return 0
        if self.fail_with:
            stage, text = self.fail_with.pop(0)
            log = self.home / "logs" / f"{stage}.log"
            log.parent.mkdir(exist_ok=True)
            log.write_text(text)
            raise RuntimeError(f"{stage} failed (exit 1). Full log: {log}")
        (self.home / "07_rigged.glb").write_bytes(b"glb" * 1000)
        (self.home / "index.html").write_text("<html>")
        (self.home / "report.json").write_text(json.dumps({
            "warnings": [],
            "stats": {"quality_game": {"silhouette_iou": 0.89, "mesh": {"triangles": 15752,
                                                                         "pieces": 1,
                                                                         "boundary_edges": 0}},
                      "rig": {"bones": 25, "weight_method": "heat",
                              "shoulder_height_fraction": 0.79, "arm_leak": 0.0,
                              "actions": ["idle", "ai3d_pose_test"]}},
        }))
        return 0


def sets(argv):
    return [argv[i + 1] for i, v in enumerate(argv) if v == "--set"]


class MakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.image = self.dir / "front.png"
        self.image.write_bytes(b"png")
        self.sunracer = self.dir / "SunRacer"
        (self.sunracer / "apps/sunracer_web/priv/static/images/game/station").mkdir(parents=True)
        self.home = self.dir / "out" / "mara"
        self.opened = []
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def maker(self, answers, extra=(), fail_with=None):
        a = arguments(["--name", "mara", "--image", str(self.image),
                       "--output-dir", str(self.dir / "out"),
                       "--sunracer", str(self.sunracer), *extra])
        replies = iter(answers)
        pipe = FakePipeline(self.home, fail_with)
        m = Maker(a, pipeline=pipe, ask=lambda _prompt: next(replies),
                  opener=self.opened.append, say=self.said.append)
        return m, pipe

    def test_full_guided_run_with_one_view_redo_and_install(self):
        m, pipe = self.maker(["back", "", "y"], extra=["--install-as", "mara_venn"])
        self.assertEqual(m.go(), 0)
        self.assertEqual(len(pipe.calls), 3)
        self.assertIn("--stop-after", pipe.calls[0])
        self.assertEqual(pipe.calls[1][pipe.calls[1].index("--redo-view") + 1], "back")
        full = pipe.calls[2]
        self.assertNotIn("--stop-after", full)
        self.assertIn("--resume", full)
        self.assertIn("retopo.texture_size=1024", sets(full))
        installed = self.sunracer / "apps/sunracer_web/priv/static/images/game/station/mara_venn.glb"
        self.assertEqual(installed.read_bytes(), (self.home / "07_rigged.glb").read_bytes())
        self.assertIn(self.home / "index.html", self.opened)
        self.assertTrue(any("01_view_back.png" in str(p) for p in self.opened))

    def test_shape_out_of_memory_falls_back_step_by_step(self):
        oom = "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 86.00 MiB"
        m, pipe = self.maker(["", "y", ""], fail_with=[("shape", oom), ("shape", oom)])
        self.assertEqual(m.go(), 0)
        full_runs = [c for c in pipe.calls if "--stop-after" not in c]
        self.assertEqual(len(full_runs), 3)
        self.assertNotIn('views.angles=["left","back"]', sets(full_runs[0]))
        self.assertIn('views.angles=["left","back"]', sets(full_runs[1]))
        self.assertIn("shape.model=mini", sets(full_runs[2]))  # no mv-turbo download here
        self.assertTrue(any("ran out of GPU memory" in s for s in self.said))

    def test_paint_out_of_memory_uses_light_settings(self):
        m, pipe = self.maker(["", "y", ""], fail_with=[("paint", "CUDA out of memory")])
        self.assertEqual(m.go(), 0)
        self.assertIn("paint.max_views=2", sets(pipe.calls[-1]))

    def test_other_failures_stop_without_retrying(self):
        m, pipe = self.maker([""], fail_with=[("rig", "Traceback: something else")])
        self.assertEqual(m.go(), 1)
        self.assertEqual(len([c for c in pipe.calls if "--stop-after" not in c]), 1)
        self.assertTrue(any("rig failed" in s for s in self.said))

    def test_stop_at_views(self):
        m, pipe = self.maker(["q"])
        self.assertEqual(m.go(), 1)
        self.assertEqual(len(pipe.calls), 1)

    def test_build_without_views(self):
        m, pipe = self.maker(["none", "y", ""])
        self.assertEqual(m.go(), 0)
        self.assertIn("views.enabled=false", sets(pipe.calls[-1]))

    def test_rejecting_the_poses_does_not_install(self):
        m, pipe = self.maker(["", "n"], extra=["--install-as", "mara_venn"])
        self.assertEqual(m.go(), 1)
        station = self.sunracer / "apps/sunracer_web/priv/static/images/game/station"
        self.assertFalse((station / "mara_venn.glb").exists())

    def test_yes_runs_unattended(self):
        m, pipe = self.maker([], extra=["--yes", "--install-as", "mara_venn.glb"])
        self.assertEqual(m.go(), 0)
        station = self.sunracer / "apps/sunracer_web/priv/static/images/game/station"
        self.assertTrue((station / "mara_venn.glb").is_file())


if __name__ == "__main__":
    unittest.main()
