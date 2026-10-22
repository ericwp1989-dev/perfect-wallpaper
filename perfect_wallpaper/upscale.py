"""Enlarging pictures with AI on the graphics card, or with a careful plain resize.

The AI runs through ncnn, a small library that uses any graphics card with Vulkan
support. A helper process (engine_server) keeps the models loaded between runs; if it
cannot start, the program falls back to realesrgan-ncnn-vulkan, the Real-ESRGAN
project's own command line engine. Every model enlarges 4 times, so a picture that
needs 2.6 times is enlarged 4 times and then shrunk to fit, which keeps the AI's detail.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import resources

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Model:
    key: str
    file: str   # name of the .param and .bin pair in engine/models
    label: str
    note: str


# Picked by a side by side test on game art and photos (October 2026).
MODELS = {
    "natural": Model("natural", "4xNomos8kSC", "Natural detail", "Photos and game art, keeps fine texture"),
    "clean": Model("clean", "4xLSDIRplusC", "Clean", "Smooth results with little noise"),
    "fast": Model("fast", "RealESRGAN_General_x4_v3", "Fast", "About five times quicker, a little softer"),
    "art": Model("art", "realesrgan-x4plus-anime", "Art and anime", "Drawings, cartoons and anime"),
}
DEFAULT_MODEL = "natural"
ALIASES = {"photo": "natural"}  # older settings files and command lines
AI_THRESHOLD = 1.15             # below this much enlargement the AI adds little
SECOND_PASS_THRESHOLD = 1.5     # run the AI twice only if one pass leaves this much to go
MAX_WORK_PIXELS = 160_000_000   # cap on the engine's output, to keep memory in check
CREATE_NO_WINDOW = 0x08000000


class Cancelled(Exception):
    pass


class EngineError(RuntimeError):
    pass


@dataclass
class Report:
    scale: float        # total enlargement
    ai_passes: int = 0  # how many times the AI ran
    note: str = ""      # why the AI was skipped, if it was wanted


def model_for(key: str) -> Model | None:
    """The model for a setting, or None for no AI. Unknown or missing models fall back."""
    key = ALIASES.get(key, key)
    if key not in MODELS:
        return None
    model = MODELS[key]
    if _model_files(model.file):
        return model
    for other in MODELS.values():  # the requested one is missing; use any that is there
        if _model_files(other.file):
            return other
    return None


def _model_files(name: str) -> bool:
    folder = resources.engine_dir() / "models"
    return (folder / f"{name}.param").exists() and (folder / f"{name}.bin").exists()


def engine_exe() -> Path | None:
    name = "realesrgan-ncnn-vulkan.exe" if sys.platform == "win32" else "realesrgan-ncnn-vulkan"
    exe = resources.engine_dir() / name
    return exe if exe.exists() else None


def ai_available() -> bool:
    return model_for(DEFAULT_MODEL) is not None and (EngineClient.possible() or engine_exe() is not None)


def enlarge(image: np.ndarray, size, enhance=DEFAULT_MODEL, progress=None, cancel=None,
            detail: float = 0.0) -> tuple[np.ndarray, Report]:
    """Scale image to exactly size (width, height), using the AI when it helps.

    detail (0 to 1) adds back some of the source's own fine texture, which the AI
    tends to smooth away."""
    h, w = image.shape[:2]
    tw, th = size
    report = Report(scale=max(tw / w, th / h))
    work = image

    model = model_for(enhance)
    want_ai = model is not None and report.scale > AI_THRESHOLD
    if want_ai and not ai_available():
        report.note = "The AI engine was not found, so a plain resize was used."
        want_ai = False
    if want_ai:
        passes = 2 if report.scale > 4 * SECOND_PASS_THRESHOLD else 1
        try:
            for i in range(passes):
                remaining = max(tw / work.shape[1], th / work.shape[0])
                work = _shrink_for_engine(work, remaining)
                work = ai_upscale(work, model.file, _part(progress, i, passes), cancel)
                report.ai_passes += 1
        except EngineError as error:
            log.warning("AI enlarge failed: %s", error)
            report.note = f"{error} A plain resize was used instead."

    if report.ai_passes:
        out = _resize(work, size)
        if detail > 0:
            out = add_texture(out, image, detail)
    else:
        out = classic_enlarge(image, size, cancel)
    if progress:
        progress(1.0)
    return out, report


def add_texture(enlarged: np.ndarray, source: np.ndarray, amount: float) -> np.ndarray:
    """Add the source's own fine texture, enlarged plainly, on top of the AI result."""
    plain = cv2.resize(source, (enlarged.shape[1], enlarged.shape[0]), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    scale = enlarged.shape[1] / source.shape[1]
    texture = plain - cv2.GaussianBlur(plain, (0, 0), max(1.0, scale * 0.9))
    return np.clip(enlarged.astype(np.float32) + texture * amount, 0, 255).astype(np.uint8)


def ai_upscale(image: np.ndarray, model: str, progress=None, cancel=None, tile: int = 0) -> np.ndarray:
    """Enlarge 4 times with the loaded engine, or with the command line engine if the
    helper is unavailable. The command line engine retries with small tiles if memory runs out."""
    client = EngineClient.shared()
    if client is not None:
        try:
            return client.upscale(image, model, progress, cancel)
        except EngineError as error:
            log.warning("Engine helper failed, using the command line engine: %s", error)
    if engine_exe() is None:
        raise EngineError("The AI engine is missing.")
    try:
        return _run_engine(image, model, progress, cancel, tile)
    except EngineError:
        if tile:
            raise
        return _run_engine(image, model, progress, cancel, tile=128)


class EngineClient:
    """Talks to the engine_server helper process, which keeps models loaded."""

    _shared: "EngineClient | None" = None
    _failed = False
    _lock = threading.Lock()

    @staticmethod
    def possible() -> bool:
        try:
            import ncnn  # noqa: F401
        except ImportError:
            return False
        return not EngineClient._failed

    @classmethod
    def shared(cls) -> "EngineClient | None":
        """The running helper, started on first use. None when it cannot run here."""
        with cls._lock:
            if cls._shared is not None and cls._shared.alive():
                return cls._shared
            if not cls.possible():
                return None
            try:
                cls._shared = EngineClient()
            except EngineError as error:
                log.warning("Engine helper unavailable: %s", error)
                cls._failed = True
                cls._shared = None
            return cls._shared

    @classmethod
    def stop_shared(cls) -> None:
        with cls._lock:
            if cls._shared is not None:
                cls._shared.close()
                cls._shared = None

    def __init__(self):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--engine-server", str(resources.engine_dir() / "models")]
        else:
            cmd = [sys.executable, "-m", "perfect_wallpaper.engine_server", str(resources.engine_dir() / "models")]
        env = dict(os.environ, PYTHONPATH=str(resources.base_dir()))
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self.replies: queue.Queue = queue.Queue()
        self.next_id = 1
        self.busy = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()
        ready = self._wait(lambda m: m.get("op") == "ready", timeout=60)
        if ready is None or ready.get("error"):
            self.close()
            raise EngineError((ready or {}).get("error") or "The engine helper did not start.")
        self.gpus = ready.get("gpus", [])
        self.gpu = ready.get("gpu")
        log.info("Engine helper ready on %s", self.gpu_name())

    def gpu_name(self) -> str:
        for gpu in self.gpus:
            if gpu["index"] == self.gpu:
                return gpu["name"]
        return "unknown"

    def alive(self) -> bool:
        return self.proc.poll() is None

    def _read(self):
        for line in self.proc.stdout:
            try:
                self.replies.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        self.replies.put({"op": "exited"})

    def _send(self, message: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as error:
            raise EngineError("The engine helper stopped.") from error

    def _wait(self, match, timeout=None):
        while True:
            try:
                message = self.replies.get(timeout=timeout)
            except queue.Empty:
                return None
            if message.get("op") == "exited":
                return message if match(message) else None
            if match(message):
                return message

    def upscale(self, image: np.ndarray, model: str, progress=None, cancel=None) -> np.ndarray:
        with self.busy, tempfile.TemporaryDirectory(prefix="perfect-wallpaper-") as tmp:
            src, dst = Path(tmp) / "in.npy", Path(tmp) / "out.npy"
            np.save(src, np.ascontiguousarray(image))
            job = self.next_id
            self.next_id += 1
            self._send({"op": "upscale", "id": job, "model": model, "input": str(src), "output": str(dst)})
            while True:
                try:
                    message = self.replies.get(timeout=0.1)
                except queue.Empty:
                    if cancel is not None and cancel.is_set():
                        self._send({"op": "cancel", "id": job})
                        cancel = None  # asked once; wait for the helper to stop
                    if not self.alive():
                        raise EngineError("The engine helper stopped.")
                    continue
                if message.get("op") == "exited":
                    raise EngineError("The engine helper stopped.")
                if message.get("id") != job:
                    continue
                if "progress" in message and progress:
                    progress(message["progress"])
                elif message.get("cancelled"):
                    raise Cancelled()
                elif message.get("error"):
                    raise EngineError(message["error"])
                elif message.get("done"):
                    return np.load(dst)

    def close(self) -> None:
        try:
            self._send({"op": "quit"})
            self.proc.wait(timeout=5)
        except (EngineError, subprocess.TimeoutExpired):
            self.proc.kill()


def _run_engine(image, model, progress, cancel, tile) -> np.ndarray:
    exe = engine_exe()
    if exe is None:
        raise EngineError("The AI engine is missing.")
    with tempfile.TemporaryDirectory(prefix="perfect-wallpaper-") as tmp:
        src, dst = Path(tmp) / "in.png", Path(tmp) / "out.png"
        _write_png(src, image)
        cmd = [
            str(exe), "-i", str(src), "-o", str(dst), "-n", model, "-s", "4",
            "-t", str(tile), "-m", str(exe.parent / "models"), "-f", "png",
        ]
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        lines: list[str] = []
        with subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            cwd=exe.parent, creationflags=flags,
        ) as proc:

            def read_progress():
                for raw in proc.stderr:
                    line = raw.decode(errors="replace").strip()
                    percent = re.fullmatch(r"(\d+(?:\.\d+)?)%", line)
                    if percent and progress:
                        progress(float(percent.group(1)) / 100)
                    elif line:
                        lines.append(line)

            reader = threading.Thread(target=read_progress, daemon=True)
            reader.start()
            while True:
                try:
                    proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if cancel is not None and cancel.is_set():
                        proc.kill()
                        raise Cancelled()
            reader.join(timeout=2)
        if proc.returncode != 0 or not dst.exists():
            raise EngineError(_explain(lines))
        return _read_png(dst)


def _explain(log: list[str]) -> str:
    text = " ".join(log).lower()
    if "vkcreateinstance" in text or "invalid gpu" in text or "no vulkan" in text:
        return "The AI engine could not use your graphics card (it needs Vulkan support)."
    if "vkallocatememory" in text or "out of memory" in text:
        return "The graphics card ran out of memory."
    detail = " ".join(log[-2:]) if log else "no details"
    return f"The AI engine stopped with an error ({detail})."


def _shrink_for_engine(image: np.ndarray, remaining: float) -> np.ndarray:
    """Shrink a big input first if its 4x output would be huge, but never below what 4x needs."""
    h, w = image.shape[:2]
    if 16 * w * h <= MAX_WORK_PIXELS:
        return image
    q = max(remaining / 4, math.sqrt(MAX_WORK_PIXELS / (16 * w * h)))
    if q >= 1:
        return image
    return cv2.resize(image, (max(1, round(w * q)), max(1, round(h * q))), interpolation=cv2.INTER_AREA)


def _part(progress, index, count):
    if progress is None:
        return None
    return lambda p: progress((index + p) / count)


def _resize(image: np.ndarray, size) -> np.ndarray:
    h, w = image.shape[:2]
    shrinking = size[0] <= w and size[1] <= h
    return cv2.resize(image, tuple(size), interpolation=cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4)


def classic_enlarge(image: np.ndarray, size, cancel=None) -> np.ndarray:
    """Resize without AI: clean up JPEG blocks, enlarge, then sharpen brightness only.
    The cleanup runs in strips so Cancel can stop a big picture partway."""
    h, w = image.shape[:2]
    scale = max(size[0] / w, size[1] / h)
    if scale <= 1:
        return _resize(image, size)
    if w * h <= 12_000_000:
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        clean = np.empty_like(bgr)
        strip, overlap = 256, 16
        for y in range(0, h, strip):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            y0, y1 = max(0, y - overlap), min(h, y + strip + overlap)
            done = cv2.fastNlMeansDenoisingColored(bgr[y0:y1], None, 2, 2, 7, 21)
            clean[y:min(h, y + strip)] = done[y - y0:y - y0 + min(strip, h - y)]
        image = cv2.cvtColor(clean, cv2.COLOR_BGR2RGB)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    big = cv2.resize(image, tuple(size), interpolation=cv2.INTER_LANCZOS4)
    lab = cv2.cvtColor(big, cv2.COLOR_RGB2LAB).astype(np.float32)
    lightness = lab[..., 0]
    lightness = _unsharp(lightness, sigma=min(6.0, 1.2 * scale), amount=0.8, threshold=2.0)
    lightness = _unsharp(lightness, sigma=max(0.8, 0.4 * scale), amount=0.6, threshold=3.0)
    lab[..., 0] = np.clip(lightness, 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)


def _unsharp(channel, sigma, amount, threshold):
    detail = channel - cv2.GaussianBlur(channel, (0, 0), sigma)
    return channel + amount * detail * (np.abs(detail) > threshold)


def _write_png(path: Path, image: np.ndarray) -> None:
    ok, data = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise EngineError("Could not prepare the picture for the AI engine.")
    data.tofile(str(path))


def _read_png(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise EngineError("The AI engine's output could not be read.")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
