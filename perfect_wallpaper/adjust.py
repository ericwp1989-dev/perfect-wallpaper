"""Final touches on the finished wallpaper: brightness, contrast, a darker strip behind
the desktop icons, and film grain. All of them work at any size, so the quick
preview and the full wallpaper look alike."""

from __future__ import annotations

import cv2
import numpy as np

ICON_STRIP = 300   # pixels at full size that Windows' first columns of desktop icons cover
ICON_FADE = 260    # how far the darkening fades out past that strip


def apply(image: np.ndarray, brightness=0.0, contrast=0.0, dim_icons=False, grain=0.0, scale=1.0) -> np.ndarray:
    """brightness and contrast run from -1 to 1, grain from 0 to 1. scale is the image's
    width over the real wallpaper's width (1 for the wallpaper itself, less for a preview)."""
    if not (brightness or contrast or dim_icons or grain):
        return image
    out = image.astype(np.float32)
    if brightness or contrast:
        out = (out - 128) * (1 + 0.7 * contrast) + 128 + 70 * brightness
    if dim_icons:
        out *= _icon_shade(out.shape[1], scale)[None, :, None]
    if grain:
        out += _grain(out.shape[:2], scale)[..., None] * (14 * grain)
    return np.clip(out, 0, 255).astype(np.uint8)


def _icon_shade(width: int, scale: float) -> np.ndarray:
    """Darkest at the left edge, where Windows lines up desktop icons, fading to nothing."""
    strip, fade = ICON_STRIP * scale, ICON_FADE * scale
    x = np.arange(width, dtype=np.float32)
    t = np.clip((x - strip) / max(fade, 1.0), 0, 1)
    smooth = t * t * (3 - 2 * t)
    return 0.55 + 0.45 * smooth


def _grain(shape, scale: float) -> np.ndarray:
    """Fine, even film grain. The same seed every time, so a remake looks identical."""
    noise = np.random.default_rng(7).standard_normal(shape).astype(np.float32)
    noise = cv2.GaussianBlur(noise, (0, 0), max(0.5, 0.8 * scale))
    return noise / (noise.std() + 1e-6)
