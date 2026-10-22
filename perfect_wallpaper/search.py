"""Finding sharper copies of a picture online.

Searches Wallhaven, a wallpaper site with a free public API, by keywords, downloads a
small preview of every result, and compares each with your picture. Copies of the same
picture are recognized even when cropped, framed differently or resized, by matching
distinctive points between the two (ORB features from OpenCV). Copies bigger than your
picture come first.

For the rest of the web, copy_to_clipboard() puts your picture on the clipboard so it
can be pasted into Google Lens or Bing Visual Search, which have no public API.
"""

from __future__ import annotations

import ctypes
import json
import logging
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import __version__

log = logging.getLogger(__name__)
API = "https://wallhaven.cc/api/v1/search"
USER_AGENT = f"PerfectWallpaper/{__version__} (desktop wallpaper tool)"
WEB_SEARCHES = {"Google Lens": "https://lens.google.com/", "Bing Visual Search": "https://www.bing.com/visualsearch"}
SAME = 0.5      # score at or above which a result counts as the same picture
SIMILAR = 0.3


@dataclass
class Candidate:
    id: str
    page_url: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    file_size: int
    source: str = "Wallhaven"
    thumb: np.ndarray | None = field(default=None, repr=False)
    score: float = 0.0

    @property
    def match(self) -> str:
        if self.score >= SAME:
            return "Same picture"
        if self.score >= SIMILAR:
            return "Similar"
        return "Different"

    def gain(self, size: tuple[int, int]) -> float:
        """How many times more pixels this copy has than a picture of size (width, height)."""
        return (self.width * self.height) / max(1, size[0] * size[1])


def suggest_keywords(name: str) -> str:
    """Search words from a file name: "red_planet-wallpaper(3).jpg" gives "red planet"."""
    words = re.sub(r"[_\-.()\[\]]+", " ", Path(name).stem).lower().split()
    noise = {"wallpaper", "wallpapers", "hd", "4k", "8k", "uhd", "img", "image", "pic", "photo", "copy", "final",
             "background", "desktop", "screenshot"}
    words = [w for w in words if w not in noise and not re.fullmatch(r"\d+(x\d+)?|\d+p", w)]
    return " ".join(words[:6])


def _get(url: str, timeout=20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def query_wallhaven(words: str, pages: int = 2) -> list[Candidate]:
    """Results for the words, safe for work only, most relevant first."""
    found: list[Candidate] = []
    for page in range(1, pages + 1):
        params = urllib.parse.urlencode({"q": words, "sorting": "relevance", "purity": "100",
                                         "categories": "111", "page": page})
        data = json.loads(_get(f"{API}?{params}"))
        for item in data.get("data", []):
            found.append(Candidate(
                id=item["id"], page_url=item["url"], image_url=item["path"],
                thumb_url=item.get("thumbs", {}).get("original") or item.get("thumbs", {}).get("large", ""),
                width=int(item["dimension_x"]), height=int(item["dimension_y"]),
                file_size=int(item.get("file_size", 0)),
            ))
        meta = data.get("meta", {})
        if page >= int(meta.get("last_page", 1)):
            break
    return found


def _decode(data: bytes) -> np.ndarray | None:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return None if image is None else cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _gray(image: np.ndarray, longest=400) -> np.ndarray:
    h, w = image.shape[:2]
    s = longest / max(w, h)
    small = cv2.resize(image, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)


class Matcher:
    """Scores how likely another picture is a copy of yours, from 0 to 1.

    SIFT points are compared at 500 pixels for both pictures; in testing that told the
    one true copy among 20 results (14 agreeing points) from the rest (2 or fewer),
    even from a 300 pixel preview of a blurry original."""

    SIZE = 500
    CHANCE = 5            # this many points can line up by coincidence between unrelated pictures
    FULL_AGREEMENT = 20

    def __init__(self, picture: np.ndarray):
        self.sift = cv2.SIFT_create(nfeatures=2000)
        self.keys, self.desc = self.sift.detectAndCompute(_gray(picture, self.SIZE), None)
        self.hist = self._hist(picture)
        self.bf = cv2.BFMatcher(cv2.NORM_L2)

    @staticmethod
    def _hist(image):
        hsv = cv2.cvtColor(cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        return cv2.normalize(hist, hist).flatten()

    def score(self, other: np.ndarray) -> float:
        colors = max(0.0, float(cv2.compareHist(self.hist, self._hist(other), cv2.HISTCMP_CORREL)))
        keys, desc = self.sift.detectAndCompute(_gray(other, self.SIZE), None)
        if self.desc is None or desc is None or len(keys) < 6:
            return 0.15 * colors
        pairs = self.bf.knnMatch(self.desc, desc, k=2)
        good = [m for m, *rest in pairs if rest and m.distance < 0.75 * rest[0].distance]
        if len(good) < 6:
            return 0.15 * colors
        a = np.float32([self.keys[m.queryIdx].pt for m in good])
        b = np.float32([keys[m.trainIdx].pt for m in good])
        # a copy differs only by size, position and a little turn: one similarity transform fits it
        _, inliers = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=4.0)
        agree = int(inliers.sum()) if inliers is not None else 0
        geometry = min(1.0, max(0, agree - self.CHANCE) / (self.FULL_AGREEMENT - self.CHANCE))
        return min(1.0, 0.85 * geometry + 0.15 * colors)


def find_copies(words: str, picture: np.ndarray, progress=None, cancel=None) -> list[Candidate]:
    """Search, score every result against picture (as it is shown, rotation included),
    and return them best first: the same picture before similar ones, bigger before smaller."""
    if progress:
        progress(0.05, "Searching Wallhaven...")
    results = query_wallhaven(words)
    if not results:
        return []
    matcher = Matcher(picture)
    done = 0

    def fetch(candidate: Candidate):
        try:
            candidate.thumb = _decode(_get(candidate.thumb_url, timeout=15))
        except OSError as error:
            log.info("Preview %s failed: %s", candidate.id, error)
        return candidate

    with ThreadPoolExecutor(max_workers=8) as pool:
        for candidate in pool.map(fetch, results):
            if cancel is not None and cancel.is_set():
                break
            if candidate.thumb is not None:
                candidate.score = matcher.score(candidate.thumb)
            done += 1
            if progress:
                progress(0.05 + 0.95 * done / len(results), f"Comparing {done} of {len(results)}...")
    ranked = [c for c in results if c.thumb is not None]
    ranked.sort(key=lambda c: (c.score >= SAME, c.score >= SIMILAR, c.width * c.height, c.score), reverse=True)
    return ranked


def download(candidate: Candidate, folder: Path) -> Path:
    """Save the full size picture into folder and return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(candidate.image_url).path).suffix or ".jpg"
    path = folder / f"{candidate.source.lower()}-{candidate.id}{suffix}"
    if not path.exists():
        path.write_bytes(_get(candidate.image_url, timeout=60))
    return path


def copy_to_clipboard(rgb: np.ndarray) -> bool:
    """Put a picture on the Windows clipboard, so it can be pasted into a web search."""
    import sys

    if sys.platform != "win32":
        return False
    ok, bmp = cv2.imencode(".bmp", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        return False
    dib = bmp.tobytes()[14:]  # the clipboard wants the bitmap without its 14 byte file header
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(dib))  # GMEM_MOVEABLE
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, dib, len(dib))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(8, handle))  # CF_DIB
    finally:
        user32.CloseClipboard()
