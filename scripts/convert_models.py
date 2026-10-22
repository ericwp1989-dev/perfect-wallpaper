"""Make the AI models from their authors' original files, so every model the program
ships comes straight from its source.

    pip install -r requirements-models.txt
    python scripts/convert_models.py

Downloads each original PyTorch file, checks its SHA256 checksum, loads it with spandrel
(which knows the network layouts) and converts it to the ncnn format with pnnx, writing
engine/models/<name>.param and .bin. The input and output are renamed "data" and
"output", the names the engine expects. Weights are stored at half precision, as in
the Real-ESRGAN project's own ncnn models.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "engine" / "models"

ORIGINALS = {
    # name in engine/models: (source URL, SHA256, author and license)
    "4xNomos8kSC": (
        "https://raw.githubusercontent.com/Phhofm/models/main/4xNomos8kSC/4xNomos8kSC.pth",
        "07a7ccd6443d012d528999cd77e40c7d265aaf1f656c499b37936e49603a0b1d",
        "Helaman (Philip Hofmann), CC BY 4.0",
    ),
    "4xLSDIRplusC": (
        "https://raw.githubusercontent.com/Phhofm/models/main/4xLSDIRplus/4xLSDIRplusC.pth",
        "a2a88864ee3561e3e48b563605e56d74e2da3fddf7dd140b301276f5c3392308",
        "Helaman (Philip Hofmann), CC BY 4.0",
    ),
    "RealESRGAN_General_x4_v3": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
        "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292",
        "Xintao Wang, BSD 3 clause",
    ),
}


def fetch(url: str, digest: str, path: Path) -> None:
    if not (path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest):
        print(f"Downloading {url}")
        with urllib.request.urlopen(url) as response, open(path, "wb") as out:
            shutil.copyfileobj(response, out)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        sys.exit(f"{path.name}: checksum does not match.")


def rename_blobs(param: Path) -> None:
    """pnnx names the input in0 and the output out0; the engine looks for data and output."""
    text = param.read_text()
    text = re.sub(r"(?<!\S)in0(?!\S)", "data", text)
    text = re.sub(r"(?<!\S)out0(?!\S)", "output", text)
    param.write_text(text)


def convert(name: str, original: Path, work: Path) -> None:
    import pnnx
    import torch
    from spandrel import ModelLoader

    descriptor = ModelLoader().load_from_file(str(original))
    if descriptor.scale != 4:
        sys.exit(f"{name}: expected a 4x model, got {descriptor.scale}x.")
    model = descriptor.model.eval().float()
    print(f"Converting {name} ({descriptor.architecture.name})")
    # pnnx writes these paths into a Python file it then runs, so they must use forward
    # slashes; Windows backslashes would read as escape codes there
    with torch.no_grad():
        pnnx.export(model, (work / f"{name}.pt").as_posix(), inputs=torch.rand(1, 3, 64, 64),
                    inputs2=torch.rand(1, 3, 96, 80), fp16=True,
                    ncnnparam=(work / f"{name}.param").as_posix(), ncnnbin=(work / f"{name}.bin").as_posix())
    rename_blobs(work / f"{name}.param")
    DEST.mkdir(parents=True, exist_ok=True)
    for suffix in (".param", ".bin"):
        shutil.copy2(work / f"{name}{suffix}", DEST / f"{name}{suffix}")


def main() -> None:
    try:
        import pnnx  # noqa: F401
        import spandrel  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        sys.exit("Converting needs PyTorch, spandrel and pnnx: pip install -r requirements-models.txt")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name, (url, digest, credit) in ORIGINALS.items():
            original = work / Path(url).name
            fetch(url, digest, original)
            convert(name, original, work)
            print(f"  {name} ready ({credit})")
    print(f"Models ready in {DEST}")


if __name__ == "__main__":
    main()
