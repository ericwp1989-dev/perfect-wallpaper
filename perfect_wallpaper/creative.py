"""The stronger AI: an optional add-on that paints in new fine detail.

It runs Stable Diffusion 1.5 with ControlNet "tile", which repaints the already enlarged
picture in small overlapping squares, keeping its shapes and colors but inventing
texture the source never had; only the finest layer of that is added to the regular AI
result (see transfer_detail). On a 5120 x 1440 wallpaper with an RTX 4060 Ti it takes
about 3.5 minutes and gives crisper grain and edges up close. It can change tiny details,
so it is off unless chosen, with a strength control.

Everything it needs, about 6 GB, is downloaded on request into
%LOCALAPPDATA%\\Perfect Wallpaper\\creative: a private copy of Python, PyTorch with
graphics card support, the diffusers library and the two models. The main program stays
small and runs the add-on as a separate process (creative_worker.py).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from . import resources
from .upscale import Cancelled

log = logging.getLogger(__name__)

PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"  # CUDA 12.6 also runs on older NVIDIA cards
PACKAGES = ["diffusers>=0.30", "transformers>=4.44", "accelerate>=0.33", "safetensors", "huggingface_hub",
            "numpy", "pillow"]
BASE_MODEL = "stable-diffusion-v1-5/stable-diffusion-v1-5"
BASE_FILES = ["model_index.json", "scheduler/*", "tokenizer/*", "feature_extractor/*", "text_encoder/config.json",
              "text_encoder/model.fp16.safetensors", "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
              "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors"]
TILE_MODEL = "lllyasviel/control_v11f1e_sd15_tile"
TILE_FILES = ["config.json", "diffusion_pytorch_model.bin"]
SIZE_TEXT = "about 6 GB"
CREATE_NO_WINDOW = 0x08000000


def home() -> Path:
    return resources.data_dir() / "creative"


def python_exe() -> Path:
    return home() / "python" / "python.exe"


def models_dir() -> Path:
    return home() / "models"


def installed() -> bool:
    return (home() / "ready.json").exists() and python_exe().exists()


def has_nvidia_card() -> bool:
    """The add-on needs an NVIDIA card (PyTorch's graphics support is built for CUDA)."""
    try:
        out = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10,
                             creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return out.returncode == 0 and "GPU" in out.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def worker_script() -> Path:
    return resources.base_dir() / "perfect_wallpaper" / "creative_worker.py"


# Installing --------------------------------------------------------------------------------

def _download(url: str, path: Path, cancel=None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "PerfectWallpaper"})
    with urllib.request.urlopen(request, timeout=60) as response, open(path, "wb") as out:
        while chunk := response.read(1 << 20):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            out.write(chunk)


def _run(args: list[str], step: str, progress, cancel) -> None:
    """Run a setup command, passing its output lines on as progress text."""
    log.info("Creative setup: %s", " ".join(args))
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1"))
    tail = []
    for line in proc.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-8:]
            if progress and (line.startswith(("Downloading", "Collecting", "Installing", "Fetching")) or "MB" in line):
                progress(None, f"{step}: {line[:90]}")
        if cancel is not None and cancel.is_set():
            proc.kill()
            raise Cancelled()
    if proc.wait() != 0:
        log.error("Creative setup step failed: %s\n%s", step, "\n".join(tail))
        raise RuntimeError(f"{step} failed: {tail[-1] if tail else 'no details'}")


def install(progress=None, cancel=None) -> None:
    """Download and set up everything the stronger AI needs. Safe to run again after a
    failure: finished steps are skipped. progress(fraction or None, text)."""
    say = progress or (lambda *_: None)
    root = home()
    root.mkdir(parents=True, exist_ok=True)
    py = python_exe()

    if not py.exists():
        say(0.01, "Downloading a private copy of Python (11 MB)...")
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "python.zip"
            _download(PYTHON_URL, archive, cancel)
            with zipfile.ZipFile(archive) as z:
                z.extractall(root / "python")
        # the embeddable Python ignores installed packages until its path file allows them
        for pth in (root / "python").glob("python*._pth"):
            lines = [ln for ln in pth.read_text().splitlines() if ln.strip() != "#import site"]
            pth.write_text("\n".join(lines + ["Lib\\site-packages", "import site"]) + "\n")

    if not (root / "python" / "Scripts" / "pip.exe").exists():
        say(0.03, "Setting up the package installer...")
        get_pip = root / "get-pip.py"
        _download(GET_PIP_URL, get_pip, cancel)
        _run([str(py), str(get_pip), "--no-warn-script-location"], "Package installer", say, cancel)

    pip = [str(py), "-m", "pip", "install", "--no-warn-script-location", "--progress-bar", "off"]
    if not (root / "python" / "Lib" / "site-packages" / "torch").exists():
        say(0.05, "Downloading PyTorch with graphics card support (2.6 GB)...")
        _run(pip + ["torch", "--index-url", TORCH_INDEX], "PyTorch", say, cancel)
    say(0.55, "Installing the image generation libraries...")
    _run(pip + PACKAGES, "Libraries", say, cancel)

    say(0.62, "Downloading Stable Diffusion 1.5 (2.0 GB) and its tile helper (1.4 GB)...")
    fetch = (
        "import sys\n"
        "from huggingface_hub import snapshot_download\n"
        f"snapshot_download({BASE_MODEL!r}, allow_patterns={BASE_FILES!r}, local_dir=sys.argv[1] + '/base')\n"
        f"snapshot_download({TILE_MODEL!r}, allow_patterns={TILE_FILES!r}, local_dir=sys.argv[1] + '/tile')\n"
    )
    _run([str(py), "-c", fetch, str(models_dir())], "Models", say, cancel)

    say(0.97, "Checking the graphics card...")
    _run([str(py), "-c", "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 3)"], "Graphics check",
         say, cancel)
    (root / "ready.json").write_text(json.dumps({"base": BASE_MODEL, "tile": TILE_MODEL}))
    say(1.0, "The stronger AI is ready.")


def remove() -> None:
    shutil.rmtree(home(), ignore_errors=True)


# Using it ----------------------------------------------------------------------------------

def refine(image: np.ndarray, strength: float, progress=None, cancel=None) -> np.ndarray:
    """Repaint fine detail into an enlarged picture. strength 0 to 1. Runs the worker in the
    add-on's own Python and returns the result, or the input unchanged if it is not installed."""
    if strength <= 0 or not installed():
        return image
    with tempfile.TemporaryDirectory(prefix="perfect-wallpaper-") as tmp:
        src, dst = Path(tmp) / "in.npy", Path(tmp) / "out.npy"
        np.save(src, np.ascontiguousarray(image))
        args = [str(python_exe()), str(worker_script()), str(models_dir()), str(src), str(dst), f"{strength:.3f}"]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        errors = []

        import threading

        def read_errors():
            for line in proc.stderr:
                errors.append(line.rstrip())
                del errors[:-20]

        threading.Thread(target=read_errors, daemon=True).start()
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            if line.startswith("progress ") and progress:
                progress(float(line.split()[1]))
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if proc.wait() != 0 or not dst.exists():
            log.error("Stronger AI failed:\n%s", "\n".join(errors))
            raise RuntimeError("The stronger AI stopped with an error. Details are in the log file.")
        return transfer_detail(image, np.load(dst), strength)


def transfer_detail(base: np.ndarray, painted: np.ndarray, strength: float) -> np.ndarray:
    """Keep the regular AI result and add only the finest texture the stronger AI painted.

    Taken whole, Stable Diffusion's version came out softer at full size (it airbrushes
    the middle sizes of detail); its finest layer, added to the regular result, gave
    crisper grain and edges in testing."""
    import cv2

    painted = painted.astype(np.float32)
    fine = painted - cv2.GaussianBlur(painted, (0, 0), 1.5)
    amount = 0.6 + 0.9 * strength
    return np.clip(base.astype(np.float32) + fine * amount, 0, 255).astype(np.uint8)
