"""Put the AI engine and its anime model in ./engine.

    python scripts/get_engine.py              download the engine
    python scripts/get_engine.py --zip FILE   use an engine zip you already downloaded

The engine is realesrgan-ncnn-vulkan (Windows build) from the official Real-ESRGAN
release; from its zip only the program, its OpenMP runtime and the anime model are kept,
after checking the zip against a known size and SHA256 checksum. The other three models
are made from their authors' original files by scripts/convert_models.py.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ENGINE_URL = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
              "realesrgan-ncnn-vulkan-20220424-windows.zip")
ENGINE_SIZE = 45_474_481
ENGINE_SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
FROM_ZIP = [
    "realesrgan-ncnn-vulkan.exe",
    "vcomp140.dll",
    "models/realesrgan-x4plus-anime.param",
    "models/realesrgan-x4plus-anime.bin",
]
DEST = Path(__file__).resolve().parent.parent / "engine"
CONVERTED = ["4xNomos8kSC", "4xLSDIRplusC", "RealESRGAN_General_x4_v3"]  # made by convert_models.py


def download(url: str, path: Path) -> None:
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as response, open(path, "wb") as out:
        shutil.copyfileobj(response, out)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_zip(path: Path) -> None:
    size = path.stat().st_size
    if size != ENGINE_SIZE:
        sys.exit(f"Unexpected engine size: {size} bytes, expected {ENGINE_SIZE}.")
    if sha256(path) != ENGINE_SHA256:
        sys.exit("The engine zip's checksum does not match.")


def extract(path: Path) -> None:
    for name in FROM_ZIP:  # replace only the engine's own files; keep converted models
        (DEST / name).unlink(missing_ok=True)
    with zipfile.ZipFile(path) as archive:
        missing = set(FROM_ZIP) - set(archive.namelist())
        if missing:
            sys.exit(f"The zip is missing: {', '.join(sorted(missing))}")
        for name in FROM_ZIP:
            target = DEST / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", type=Path, help="use this engine zip instead of downloading it")
    args = parser.parse_args()
    if args.zip:
        verify_zip(args.zip)
        extract(args.zip)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "engine.zip"
            download(ENGINE_URL, path)
            verify_zip(path)
            extract(path)
    print(f"Engine ready in {DEST}")
    missing = [m for m in CONVERTED if not (DEST / "models" / f"{m}.bin").exists()]
    if missing:
        print(f"Still needed: {', '.join(missing)}. Run: python scripts/convert_models.py")


if __name__ == "__main__":
    main()
