"""Checks for placement, compositing and resizing. Run: python -m unittest discover -s tests"""

import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from perfect_wallpaper import fitting, pipeline, upscale  # noqa: E402


def noise(w, h, seed=0):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


class PlanTests(unittest.TestCase):
    def test_fill_keeps_the_screen_shape(self):
        plan = fitting.make_plan((2000, 563), (5120, 1440), "fill")
        left, top, right, bottom = plan.crop
        self.assertEqual(plan.size, (5120, 1440))
        self.assertAlmostEqual((right - left) / (bottom - top), 5120 / 1440, delta=0.01)
        self.assertAlmostEqual(plan.scale, 2.56, places=2)

    def test_fill_focus_stays_inside_the_picture(self):
        for focus in [(0, 0), (1, 1), (-5, 9), (0.5, 0.5)]:
            left, top, right, bottom = fitting.make_plan((1000, 3000), (1920, 1080), "fill", focus).crop
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(right, 1000)
            self.assertLessEqual(bottom, 3000)

    def test_fit_modes_center_the_whole_picture(self):
        plan = fitting.make_plan((1000, 1000), (1920, 1080), "blur")
        self.assertEqual(plan.crop, (0, 0, 1000, 1000))
        self.assertEqual(plan.size, (1080, 1080))
        self.assertEqual(plan.offset, (420, 0))

    def test_pan_moves_against_the_drag_and_clamps(self):
        start = (0.5, 0.5)
        moved = fitting.pan((1000, 3000), (1920, 1080), start, dx=0, dy=0.1)
        self.assertLess(moved[1], start[1])
        far = fitting.pan((1000, 3000), (1920, 1080), start, dx=0, dy=-50)
        self.assertEqual(far, fitting.clamp_focus((1000, 3000), (1920, 1080), (0.5, 1.0)))

    def test_smart_focus_finds_the_busy_part(self):
        picture = np.full((300, 1200, 3), 30, np.uint8)
        picture[:, 900:1100] = noise(200, 300)
        fx, _ = fitting.smart_focus(picture, (600, 300))
        self.assertGreater(fx, 0.6)


class ComposeTests(unittest.TestCase):
    def test_every_mode_returns_exactly_the_screen_size(self):
        picture = noise(400, 300)
        for mode in fitting.MODES:
            out = pipeline.preview(picture, pipeline.Settings(target=(1280, 400), mode=mode), (1280, 400))
            self.assertEqual(out.shape, (400, 1280, 3), mode)

    def test_full_render_without_ai_matches_the_target(self):
        picture = noise(300, 200)
        for mode in fitting.MODES:
            out, report = pipeline.render(picture, pipeline.Settings(target=(800, 300), mode=mode, enhance="off"))
            self.assertEqual(out.shape, (300, 800, 3), mode)
            self.assertEqual(report.ai_passes, 0)


class ResizeTests(unittest.TestCase):
    def test_shrinking_skips_the_ai(self):
        out, report = upscale.enlarge(noise(800, 600), (400, 300), "photo")
        self.assertEqual(out.shape, (300, 400, 3))
        self.assertEqual(report.ai_passes, 0)

    def test_rotation_turns_counterclockwise(self):
        picture = np.zeros((2, 3, 3), np.uint8)
        picture[0, 2] = 255  # top right corner
        turned = pipeline.rotate(picture, 90)
        self.assertEqual(turned.shape, (3, 2, 3))
        self.assertTrue((turned[0, 0] == 255).all())  # top right ends up top left

    @unittest.skipUnless(upscale.engine_exe(), "AI engine not installed")
    @unittest.skipIf(os.environ.get("CI"), "build servers have no graphics card")
    def test_ai_upscale_runs_on_the_engine(self):
        out, report = upscale.enlarge(noise(64, 48), (200, 150), "photo")
        self.assertEqual(out.shape, (150, 200, 3))
        self.assertEqual(report.ai_passes, 1, report.note)


if __name__ == "__main__":
    unittest.main()
