"""Checks for the features added in the second round. Run: python -m unittest discover -s tests"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from perfect_wallpaper import adjust, fitting, pipeline, resources, screens, search, state, upscale  # noqa: E402


def noise(w, h, seed=0):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def scene(w=600, h=400, seed=1):
    """A picture with real structure (shapes at many sizes), so feature matching has something to find."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 30, np.uint8)
    for _ in range(80):
        x, y, r = int(rng.integers(0, w)), int(rng.integers(0, h)), int(rng.integers(4, 40))
        cv2.circle(img, (x, y), r, tuple(int(c) for c in rng.integers(40, 255, 3)), -1)
        cv2.line(img, (x, y), (int(rng.integers(0, w)), int(rng.integers(0, h))),
                 tuple(int(c) for c in rng.integers(40, 255, 3)), 2)
    return img


class ZoomTests(unittest.TestCase):
    def test_zoom_keeps_a_smaller_part(self):
        wide = fitting.crop_extent((2000, 1000), (1920, 1080))
        zoomed = fitting.crop_extent((2000, 1000), (1920, 1080), zoom=2.0)
        self.assertAlmostEqual(zoomed[0], wide[0] / 2, places=3)
        self.assertAlmostEqual(zoomed[1], wide[1] / 2, places=3)

    def test_zoomed_plan_stays_inside_and_keeps_the_screen_shape(self):
        for focus in [(0, 0), (1, 1), (0.5, 0.5)]:
            plan = fitting.make_plan((2000, 1000), (1920, 1080), "fill", focus, zoom=3.0)
            left, top, right, bottom = plan.crop
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(right, 2000)
            self.assertLessEqual(bottom, 1000)
            self.assertAlmostEqual((right - left) / (bottom - top), 1920 / 1080, delta=0.02)


class MirrorTests(unittest.TestCase):
    def test_a_narrow_picture_on_a_very_wide_screen_is_mirrored_once_at_most(self):
        picture = noise(200, 600)
        settings = pipeline.Settings(target=(3200, 600), mode="mirror")
        out = pipeline.preview(picture, settings, (3200, 600))
        self.assertEqual(out.shape, (600, 3200, 3))
        # far from the picture the backdrop is a smooth blur, not more copies of the noise
        far_edge = out[:, :300].astype(np.float32)
        self.assertLess(np.abs(np.diff(far_edge, axis=1)).mean(), 8)

    def test_one_reflection_is_used_when_it_covers_the_gaps(self):
        picture = noise(400, 300)
        out = pipeline.preview(picture, pipeline.Settings(target=(600, 300), mode="mirror"), (600, 300))
        self.assertEqual(out.shape, (300, 600, 3))

    def test_a_big_bright_subject_near_the_edge_is_not_copied_onto_the_side(self):
        # a dark picture with a big bright disk near its left edge, like a star in space
        picture = np.full((270, 640, 3), 12, np.uint8)
        cv2.circle(picture, (200, 135), 90, (235, 235, 235), -1)
        out = pipeline.preview(picture, pipeline.Settings(target=(1600, 360), mode="mirror"), (1600, 360))
        self.assertEqual(out.shape, (360, 1600, 3))
        # a full reflection would put a bright half disk in the outer half of the left side
        self.assertLess(out[:, :180].max(), 60)
        plan = fitting.make_plan((640, 270), (1600, 360), "mirror")
        self.assertTrue(fitting.mirror_stops_short(picture, plan))
        # plain texture still gets the whole reflection
        self.assertFalse(fitting.mirror_stops_short(noise(640, 270), plan))


class LookTests(unittest.TestCase):
    def test_nothing_changes_when_every_control_is_neutral(self):
        image = noise(50, 40)
        self.assertIs(adjust.apply(image), image)

    def test_brightness_contrast_dimming_and_grain(self):
        image = np.full((100, 2000, 3), 128, np.uint8)
        self.assertGreater(adjust.apply(image, brightness=0.5).mean(), image.mean())
        dimmed = adjust.apply(image, dim_icons=True)
        self.assertLess(dimmed[:, :100].mean(), dimmed[:, -100:].mean())
        self.assertGreater(adjust.apply(image, grain=1.0).std(), image.std())
        contrasted = adjust.apply(np.tile(np.array([100, 156], np.uint8)[None, :, None], (1, 1, 3)), contrast=0.5)
        self.assertGreater(int(contrasted[0, 1, 0]) - int(contrasted[0, 0, 0]), 56)


class FileTests(unittest.TestCase):
    def test_unique_path_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "picture 5120x1440.png"
            self.assertEqual(pipeline.unique_path(first), first)
            first.write_bytes(b"x")
            second = pipeline.unique_path(first)
            self.assertEqual(second.name, "picture 5120x1440 2.png")
            second.write_bytes(b"x")
            self.assertEqual(pipeline.unique_path(first).name, "picture 5120x1440 3.png")

    def test_settings_and_history_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = resources.data_dir
            resources.data_dir = lambda: Path(tmp)
            try:
                made = Path(tmp) / "made.png"
                made.write_bytes(b"x")
                data = {"settings": {"mode": "blur"}}
                state.add_history(data, made, "source.jpg", {"mode": "blur"})
                state.save(data)
                loaded = state.load()
                self.assertEqual(loaded["settings"]["mode"], "blur")
                self.assertEqual(state.history(loaded)[0]["path"], str(made))
                made.unlink()
                self.assertEqual(state.history(loaded), [])  # deleted files drop out
            finally:
                resources.data_dir = original


class SpanTests(unittest.TestCase):
    def screens(self):
        return [screens.Screen("Display 1", "A", 0, 0, 1920, 1080, True),
                screens.Screen("Display 2", "B", 1920, 0, 1920, 1080, False)]

    def test_gaps_widen_the_picture_and_are_cut_back_out(self):
        two = self.screens()
        self.assertEqual(screens.span_size(two, 0), (3840, 1080))
        self.assertEqual(screens.span_size(two, 50), (3890, 1080))
        wide = np.zeros((1080, 3890, 3), np.uint8)
        wide[:, 1920:1970] = 255  # the strip hidden behind the monitor frames
        out = screens.cut_gaps(wide, two, 50)
        self.assertEqual(out.shape, (1080, 3840, 3))
        self.assertEqual(out.max(), 0)


class SearchTests(unittest.TestCase):
    def test_keywords_come_from_the_file_name(self):
        self.assertEqual(search.suggest_keywords("red_planet-wallpaper(3) 1920x1080.jpg"), "red planet")
        self.assertEqual(search.suggest_keywords("1.jpg"), "")

    def test_a_resized_crop_matches_and_a_different_picture_does_not(self):
        original = scene(seed=1)
        matcher = search.Matcher(original)
        copy = cv2.resize(original[40:360, 60:560], (1000, 640), interpolation=cv2.INTER_CUBIC)
        self.assertGreaterEqual(matcher.score(copy), search.SAME)
        self.assertLess(matcher.score(scene(seed=2)), search.SIMILAR)


class ModelTests(unittest.TestCase):
    def test_old_names_and_off(self):
        self.assertIsNone(upscale.model_for("off"))
        if upscale.model_for("natural"):
            self.assertEqual(upscale.model_for("photo"), upscale.model_for("natural"))

    def test_texture_is_added_without_changing_the_size(self):
        enlarged = np.full((200, 300, 3), 128, np.uint8)
        out = upscale.add_texture(enlarged, noise(75, 50), 0.5)
        self.assertEqual(out.shape, enlarged.shape)
        self.assertGreater(out.std(), 0)

    def test_cancel_stops_a_plain_resize(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(upscale.Cancelled):
            upscale.classic_enlarge(noise(600, 400), (1800, 1200), cancel)

    def test_render_with_every_new_setting(self):
        settings = pipeline.Settings(target=(800, 300), mode="fill", enhance="off", zoom=1.5, detail=0.5, grain=0.3,
                                     brightness=0.2, contrast=-0.2, dim_icons=True)
        out, _ = pipeline.render(noise(400, 300), settings)
        self.assertEqual(out.shape, (300, 800, 3))


if __name__ == "__main__":
    unittest.main()
