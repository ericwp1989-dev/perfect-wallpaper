"""From a picture to a finished wallpaper: rotate, place, enlarge, fill, finish, save."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import adjust, fitting, upscale

Image.MAX_IMAGE_PIXELS = 400_000_000

try:  # iPhone photos (HEIC and HEIF)
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC = True
except ImportError:
    HEIC = False

PICTURE_PATTERNS = "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tif *.tiff" + (" *.heic *.heif" if HEIC else "")
ENHANCERS = {**{m.key: m.label for m in upscale.MODELS.values()}, "off": "Off (no AI)"}


@dataclass(frozen=True)
class Settings:
    target: tuple[int, int]
    mode: str = "fill"
    rotation: int = 0                        # degrees counterclockwise: 0, 90, 180 or 270
    focus: tuple[float, float] | None = None  # where Fill mode centers; None picks automatically
    enhance: str = upscale.DEFAULT_MODEL     # an AI model key, or "off"
    zoom: float = 1.0                        # Fill mode only: above 1 keeps a smaller part
    detail: float = 0.0                      # 0 to 1: the source's own texture added back
    grain: float = 0.0                       # 0 to 1: film grain
    brightness: float = 0.0                  # -1 to 1
    contrast: float = 0.0                    # -1 to 1
    dim_icons: bool = False                  # darken the strip behind desktop icons
    creative: float = 0.0                    # 0 to 1: the stronger AI's strength; 0 is off


def load_picture(path) -> np.ndarray:
    with Image.open(path) as image:
        return to_rgb(ImageOps.exif_transpose(image))


def to_rgb(image: Image.Image) -> np.ndarray:
    """RGB pixels, with any transparency laid over black."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        image = Image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 255)), image.convert("RGBA"))
    return np.array(image.convert("RGB"))


def rotate(picture: np.ndarray, rotation: int) -> np.ndarray:
    turns = (rotation // 90) % 4
    return np.ascontiguousarray(np.rot90(picture, turns)) if turns else picture


def shrink(picture: np.ndarray, longest: int) -> np.ndarray:
    h, w = picture.shape[:2]
    s = longest / max(w, h)
    if s >= 1:
        return picture
    return cv2.resize(picture, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


def _focus(pic: np.ndarray, settings: Settings):
    return settings.focus or fitting.smart_focus(shrink(pic, 800), settings.target, settings.zoom)


def plan_for(picture: np.ndarray, settings: Settings) -> fitting.Plan:
    """The placement for the rotated picture, picking a focus automatically if needed."""
    pic = rotate(picture, settings.rotation)
    return fitting.make_plan((pic.shape[1], pic.shape[0]), settings.target, settings.mode, _focus(pic, settings),
                             settings.zoom)


def finish(image: np.ndarray, settings: Settings, scale: float = 1.0) -> np.ndarray:
    return adjust.apply(image, settings.brightness, settings.contrast, settings.dim_icons, settings.grain, scale)


def render(picture: np.ndarray, settings: Settings, progress=None, cancel=None):
    """The full size wallpaper as an RGB array, plus a report on how it was enlarged."""
    pic = rotate(picture, settings.rotation)
    plan = fitting.make_plan((pic.shape[1], pic.shape[0]), settings.target, settings.mode, _focus(pic, settings),
                             settings.zoom)
    left, top, right, bottom = plan.crop
    region = pic[top:bottom, left:right]
    creative = settings.creative > 0
    split = (lambda p: progress(p * 0.5)) if (progress and creative) else progress
    placed, report = upscale.enlarge(region, plan.size, settings.enhance, split, cancel, settings.detail)
    if creative:
        from . import creative as creative_ai

        # Stable Diffusion needs the graphics card's memory to itself; sharing it with the
        # loaded upscaling models made it four times slower in testing
        upscale.EngineClient.stop_shared()
        placed = creative_ai.refine(placed, settings.creative,
                                    progress=(lambda p: progress(0.5 + p * 0.5)) if progress else None,
                                    cancel=cancel)
    if cancel is not None and cancel.is_set():
        raise upscale.Cancelled()
    return finish(fitting.compose(pic, placed, plan, settings.mode), settings), report


def preview(picture: np.ndarray, settings: Settings, box) -> np.ndarray:
    """A quick, small render without AI that fits inside box (width, height).

    Pass a reduced copy of the picture for speed; placement is proportional, so the
    preview matches the full render.
    """
    tw, th = settings.target
    s = min(box[0] / tw, box[1] / th)
    size = (max(1, round(tw * s)), max(1, round(th * s)))
    pic = rotate(picture, settings.rotation)
    plan = fitting.make_plan((pic.shape[1], pic.shape[0]), size, settings.mode, settings.focus or (0.5, 0.5),
                             settings.zoom)
    left, top, right, bottom = plan.crop
    interpolation = cv2.INTER_AREA if plan.scale < 1 else cv2.INTER_LINEAR
    placed = cv2.resize(pic[top:bottom, left:right], plan.size, interpolation=interpolation)
    return finish(fitting.compose(pic, placed, plan, settings.mode), settings, scale=size[0] / tw)


def unique_path(path: Path) -> Path:
    """path itself if it is free, else the same name with 2, 3 and so on added."""
    path = Path(path)
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem} {n}{path.suffix}")).exists():
        n += 1
    return candidate


def save(image: np.ndarray, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    picture = Image.fromarray(image)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        picture.save(path, quality=95, subsampling=0)
    else:
        picture.save(path, compress_level=6)
    return path
