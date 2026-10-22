"""How a picture is placed on a screen of a different shape.

Everything here works on sizes and NumPy arrays in RGB order, so the same code builds
the quick preview and the full size wallpaper. Sizes are (width, height) in pixels and
focus points are fractions of the picture's width and height.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MODES = {
    "fill": "Fill the screen (crop)",
    "blur": "Show it all, blurred sides",
    "mirror": "Show it all, mirrored sides",
    "bars": "Show it all, black bars",
}


@dataclass(frozen=True)
class Plan:
    crop: tuple[int, int, int, int]  # part of the picture used: left, top, right, bottom
    size: tuple[int, int]            # size that part is scaled to
    offset: tuple[int, int]          # where it lands on the screen
    target: tuple[int, int]          # screen size

    @property
    def scale(self) -> float:
        """How much the picture is enlarged; below 1 means it is shrunk."""
        left, top, right, bottom = self.crop
        return max(self.size[0] / (right - left), self.size[1] / (bottom - top))


def _clamp(value, low, high):
    return max(low, min(high, value))


MAX_ZOOM = 4.0


def crop_extent(src_size, target, zoom=1.0) -> tuple[float, float]:
    """Fraction of the picture's width and height that Fill mode keeps. Zoom above 1
    keeps a smaller part of the picture, as if leaning in."""
    w, h = src_size
    tw, th = target
    s = max(tw / w, th / h) * _clamp(zoom, 1.0, MAX_ZOOM)
    return min(1.0, tw / s / w), min(1.0, th / s / h)


def clamp_focus(src_size, target, focus, zoom=1.0) -> tuple[float, float]:
    """Keep the Fill crop inside the picture."""
    fw, fh = crop_extent(src_size, target, zoom)
    return _clamp(focus[0], fw / 2, 1 - fw / 2), _clamp(focus[1], fh / 2, 1 - fh / 2)


def pan(src_size, target, focus, dx, dy, zoom=1.0) -> tuple[float, float]:
    """Move the Fill crop when the preview is dragged by (dx, dy) fractions of its size."""
    fw, fh = crop_extent(src_size, target, zoom)
    return clamp_focus(src_size, target, (focus[0] - dx * fw, focus[1] - dy * fh), zoom)


def make_plan(src_size, target, mode, focus=(0.5, 0.5), zoom=1.0) -> Plan:
    w, h = src_size
    tw, th = target
    if mode == "fill":
        fw, fh = crop_extent(src_size, target, zoom)
        fx, fy = clamp_focus(src_size, target, focus, zoom)
        cw = _clamp(round(fw * w), 1, w)
        ch = _clamp(round(fh * h), 1, h)
        left = _clamp(round(fx * w - cw / 2), 0, w - cw)
        top = _clamp(round(fy * h - ch / 2), 0, h - ch)
        return Plan((left, top, left + cw, top + ch), (tw, th), (0, 0), (tw, th))
    s = min(tw / w, th / h)
    sw = _clamp(round(w * s), 1, tw)
    sh = _clamp(round(h * s), 1, th)
    return Plan((0, 0, w, h), (sw, sh), ((tw - sw) // 2, (th - sh) // 2), (tw, th))


# Choosing what Fill mode keeps ------------------------------------------------------

def smart_focus(picture: np.ndarray, target, zoom=1.0) -> tuple[float, float]:
    """Center Fill mode's crop on faces, or else on the most detailed, colorful part.

    Skin tones count extra so people are not cut off, and a mild pull toward the
    middle keeps the choice from drifting to a busy edge.
    """
    h, w = picture.shape[:2]
    fw, fh = crop_extent((w, h), target, zoom)
    if fw > 0.995 and fh > 0.995:
        return 0.5, 0.5

    s = min(1.0, 400 / max(w, h))
    small = cv2.resize(picture, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    energy = _energy(small)
    sh, sw = energy.shape
    face_mask = np.zeros_like(energy)
    for fx, fy, fwid, fhei in find_faces(picture):
        # the head and shoulders around each face, in the small copy's pixels
        cx, cy = (fx + fwid / 2) / w * sw, (fy + fhei / 2) / h * sh
        rx, ry = fwid / w * sw * 0.8, fhei / h * sh * 1.0
        face_mask[max(0, int(cy - ry)):int(cy + ry * 1.6), max(0, int(cx - rx)):int(cx + rx)] = 1
    if face_mask.any():
        energy = energy + face_mask * energy.max() * 2
    cw, ch = _clamp(round(fw * sw), 1, sw), _clamp(round(fh * sh), 1, sh)

    sums = cv2.integral(energy)
    xs = np.unique(np.linspace(0, sw - cw, num=min(81, sw - cw + 1)).round().astype(int))
    ys = np.unique(np.linspace(0, sh - ch, num=min(81, sh - ch + 1)).round().astype(int))
    best, best_xy = -1.0, (0, 0)
    for y in ys:
        for x in xs:
            score = sums[y + ch, x + cw] - sums[y, x + cw] - sums[y + ch, x] + sums[y, x]
            if score > best:
                best, best_xy = score, (x, y)
    x, y = best_xy
    return clamp_focus((w, h), target, ((x + cw / 2) / sw, (y + ch / 2) / sh), zoom)


_face_detector = None


def find_faces(picture: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Faces as (x, y, width, height) in the picture's pixels, using OpenCV's YuNet model.
    Returns nothing when the model file is missing."""
    global _face_detector
    from . import resources

    model = resources.asset("face_detection_yunet_2023mar.onnx")
    if not model.exists() or not hasattr(cv2, "FaceDetectorYN"):
        return []
    h, w = picture.shape[:2]
    s = min(1.0, 640 / max(w, h))
    small = cv2.resize(picture, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    try:
        if _face_detector is None:
            _face_detector = cv2.FaceDetectorYN.create(str(model), "", (bgr.shape[1], bgr.shape[0]), 0.75)
        _face_detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, found = _face_detector.detect(bgr)
    except cv2.error:
        return []
    if found is None:
        return []
    return [(int(f[0] / s), int(f[1] / s), int(f[2] / s), int(f[3] / s)) for f in found]


def _energy(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    detail = cv2.GaussianBlur(cv2.magnitude(gx, gy), (0, 0), 2)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32) / 255
    color = hsv[..., 1] * hsv[..., 2]

    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin = cv2.inRange(ycrcb, (40, 135, 85), (240, 175, 130)).astype(np.float32) / 255
    skin = cv2.GaussianBlur(skin, (0, 0), 3)

    energy = detail / (detail.mean() + 1e-6) + 0.5 * color / (color.mean() + 1e-6) + 1.5 * skin

    h, w = energy.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    middle = np.exp(-(((xx / w - 0.5) ** 2) + ((yy / h - 0.5) ** 2)) / (2 * 0.35**2))
    return (energy * (0.6 + 0.4 * middle)).astype(np.float32)


# Filling whatever the picture leaves uncovered -----------------------------------------

def compose(picture: np.ndarray, placed: np.ndarray, plan: Plan, mode: str) -> np.ndarray:
    """Put the scaled picture on a screen sized canvas and fill the rest.

    picture is the whole source (used to paint the blurred backdrop); placed is the
    part named by plan.crop, already scaled to plan.size.
    """
    tw, th = plan.target
    x, y = plan.offset
    pw, ph = plan.size
    if (pw, ph) == (tw, th):
        return placed
    if mode == "mirror":
        return _mirror(picture, placed, plan)
    canvas = _blurred_backdrop(picture, (tw, th)) if mode == "blur" else np.zeros((th, tw, 3), np.uint8)
    canvas[y:y + ph, x:x + pw] = placed
    return canvas


def _gaps(plan: Plan) -> tuple[int, int, int, int]:
    """The uncovered space on each side of the picture: left, right, top, bottom."""
    tw, th = plan.target
    x, y = plan.offset
    pw, ph = plan.size
    return x, tw - pw - x, y, th - ph - y


def _one_reflection(plan: Plan) -> tuple[int, int, int, int]:
    """How far a single reflection of the picture reaches into each gap."""
    pw, ph = plan.size
    gaps = _gaps(plan)
    return min(gaps[0], pw), min(gaps[1], pw), min(gaps[2], ph), min(gaps[3], ph)


def mirror_pads(picture: np.ndarray, plan: Plan) -> tuple[int, int, int, int]:
    """How far Mirrored sides reflects the picture into each gap (left, right, top,
    bottom), in screen pixels.

    One reflection at most, and less when a large subject, such as a big star in dark
    space, sits near the edge inside the strip that would be reflected: the copy would
    show a second, cut off subject at the end of the screen. The reflection then stops
    in the calm part before the subject and a blur of that calm part takes over.
    """
    pads = _one_reflection(plan)
    if not any(pads):
        return pads
    pw, ph = plan.size
    gray = _calm_gray(picture)
    left, right = _calm_reach(gray, pads[0] / pw, pads[1] / pw)
    top, bottom = _calm_reach(gray.T, pads[2] / ph, pads[3] / ph)
    reach = (left * pw, right * pw, top * ph, bottom * ph)
    return tuple(min(pad, int(r)) for pad, r in zip(pads, reach))


def mirror_stops_short(picture: np.ndarray, plan: Plan) -> bool:
    """Whether a large subject near an edge keeps Mirrored sides from filling the gaps
    with a full reflection, so Blurred sides may look better."""
    return mirror_pads(picture, plan) != _one_reflection(plan)


_CALM_SIDE = 160   # short side of the small copy the subject check works on
_CALM = 0.03       # average change in brightness (0 to 1) from the edge that is still calm
_SUBJECT = 0.08    # a change this big is a subject, if it comes on quickly after a calm stretch
_BIG = 0.2         # a quick change this big is a subject even right beside the edge


def _calm_gray(picture: np.ndarray) -> np.ndarray:
    """A small, softened grayscale copy. Its size depends only on the picture's shape, so
    the preview and the full size wallpaper make the same choice."""
    h, w = picture.shape[:2]
    s = _CALM_SIDE / min(w, h)
    small = cv2.resize(picture, (max(1, round(w * s)), max(1, round(h * s))),
                       interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    return cv2.GaussianBlur(gray, (0, 0), 4)


def _calm_reach(gray: np.ndarray, left: float, right: float) -> tuple[float, float]:
    """How far in from its left and right edges gray can be mirrored, as fractions of its
    width, looking only as far as the fractions asked for (1 means no limit).

    Each column is compared with the edge itself, row by row. A subject is a big change
    that comes on within a short distance after a long calm stretch, like the rim of a
    star after empty space. Landscapes change little by little and keep their whole
    reflection, and stars, grass, noise and other fine texture are blurred away. Close
    to the edge there is little calm to go by, so there the change must be bigger.
    """
    h, w = gray.shape
    short = min(h, w)
    rise, settled = max(2, round(0.12 * short)), round(0.15 * short)
    edge_width = max(2, round(0.03 * w))
    reach = []
    for want, side in ((left, gray), (right, gray[:, ::-1])):
        n = min(w, int(np.ceil(want * w)))
        edge = side[:, :edge_width].mean(axis=1, keepdims=True)
        change = np.abs(side[:, :n] - edge).mean(axis=0)
        reach.append(1.0)
        subject = np.flatnonzero(change > _SUBJECT)
        if subject.size:
            start = subject[0]
            calm = np.flatnonzero(change[:start] < _CALM)
            last_calm = int(calm[-1]) if calm.size else 0
            jump = change[min(n - 1, last_calm + rise)] - change[last_calm]
            if start - last_calm <= rise and (last_calm >= settled or jump >= _BIG):
                reach[-1] = last_calm / w
    return reach[0], reach[1]


def _mirror(picture: np.ndarray, placed: np.ndarray, plan: Plan) -> np.ndarray:
    """Mirror the picture into the gaps once at most, and only up to any large subject
    near an edge. A tall picture on a very wide screen would otherwise repeat like a
    kaleidoscope, so past the reflection the blurred backdrop takes over, with a soft
    fade between the two.

    Where a subject cut the reflection short, the rest of that gap is a blur of the calm
    edge strip instead, because the backdrop is the whole picture stretched, and it
    would push a subject near the edge out into the gap as a big blurred copy."""
    tw, th = plan.target
    x, y = plan.offset
    pw, ph = plan.size
    gaps = _gaps(plan)
    pads = mirror_pads(picture, plan)
    band = cv2.copyMakeBorder(placed, pads[2], pads[3], pads[0], pads[1], cv2.BORDER_REFLECT)
    if pads == gaps:
        return _soften_outside(band, plan)

    canvas = _blurred_backdrop(picture, (tw, th))
    side = min(tw, th)
    thin = max(2, min(pw, ph) // 50)  # the edge itself, when the subject touches it
    for edge, (pad, whole) in enumerate(zip(pads, _one_reflection(plan))):
        if pad >= whole:
            continue
        n, gap = max(pad, thin), gaps[edge]
        # full brightness beside the picture, so there is no step where nothing is mirrored,
        # and as dim as the backdrop at the edge of the screen
        dim = np.linspace(0.6, 1, gap, dtype=np.float32)
        if edge == 0:
            canvas[y:y + ph, :x] = _blurred(cv2.flip(placed[:, :n], 1), (gap, ph), side, dim[None, :, None])
        elif edge == 1:
            canvas[y:y + ph, x + pw:] = _blurred(cv2.flip(placed[:, pw - n:], 1), (gap, ph), side,
                                                 dim[None, ::-1, None])
        elif edge == 2:
            canvas[:y, x:x + pw] = _blurred(cv2.flip(placed[:n], 0), (pw, gap), side, dim[:, None, None])
        else:
            canvas[y + ph:, x:x + pw] = _blurred(cv2.flip(placed[ph - n:], 0), (pw, gap), side, dim[::-1, None, None])
    bh, bw = band.shape[:2]
    fade = max(8, min(tw, th) // 12)
    across, down = np.ones(bw, np.float32), np.ones(bh, np.float32)
    for edge, (pad, gap) in enumerate(zip(pads, gaps)):
        if pad < gap and pad > 0:
            n = min(fade, pad)
            ramp = np.linspace(0, 1, n, dtype=np.float32)
            if edge == 0:
                across[:n] = ramp
            elif edge == 1:
                across[-n:] = ramp[::-1]
            elif edge == 2:
                down[:n] = ramp
            else:
                down[-n:] = ramp[::-1]
    alpha = np.outer(down, across)[..., None]
    top, left = y - pads[2], x - pads[0]
    region = canvas[top:top + bh, left:left + bw].astype(np.float32)
    canvas[top:top + bh, left:left + bw] = (region * (1 - alpha) + band.astype(np.float32) * alpha).astype(np.uint8)
    return _soften_outside(canvas, plan)


def _blurred_backdrop(picture: np.ndarray, target) -> np.ndarray:
    """The picture stretched to fill the screen, heavily blurred and dimmed."""
    h, w = picture.shape[:2]
    left, top, right, bottom = make_plan((w, h), target, "fill").crop
    return _blurred(picture[top:bottom, left:right], target, min(target))


def _blurred(picture: np.ndarray, size, screen_side: int, dim=0.6) -> np.ndarray:
    """picture stretched to size (width, height), heavily blurred and dimmed. dim may be
    an array, to dim some parts more than others."""
    w, h = size
    small = cv2.resize(picture, (max(8, w // 12), max(8, h // 12)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 3)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (0, 0), max(2.0, screen_side / 200))
    return (big.astype(np.float32) * dim).astype(np.uint8)


def _soften_outside(canvas: np.ndarray, plan: Plan) -> np.ndarray:
    """Blur and dim the mirrored areas a little more the farther they are from the picture."""
    tw, th = plan.target
    x, y = plan.offset
    pw, ph = plan.size
    outside = np.full((th, tw), 255, np.uint8)
    outside[y:y + ph, x:x + pw] = 0
    distance = cv2.distanceTransform(outside, cv2.DIST_L2, 3)
    ramp = np.clip(distance / max(8.0, min(tw, th) / 10), 0, 1)[..., None]
    blurred = cv2.GaussianBlur(canvas, (0, 0), max(2.0, min(tw, th) / 120)).astype(np.float32)
    out = canvas.astype(np.float32) * (1 - 0.8 * ramp) + blurred * (0.8 * ramp)
    out *= 1 - 0.25 * ramp
    return np.clip(out, 0, 255).astype(np.uint8)
