"""Build Perfect Wallpaper for Windows.

    python scripts/build.py              both: dist/PerfectWallpaper.exe and the installer
    python scripts/build.py --portable   only the single file, dist/PerfectWallpaper.exe
    python scripts/build.py --installer  only dist/PerfectWallpaper-Setup-<version>.exe

The portable file unpacks itself on every start (about 4 seconds); the installed program
opens about twice as fast. The installer needs Inno Setup 6 (https://jrsoftware.org).
Run scripts/get_engine.py first. Build files go to ./build.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from perfect_wallpaper import __version__  # noqa: E402

ISCC_PLACES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
]


def pyinstaller(onefile: bool) -> None:
    sep = os.pathsep  # PyInstaller's source;destination separator
    PyInstaller.__main__.run([
        str(ROOT / "launcher.py"),
        "--name", "PerfectWallpaper",
        "--onefile" if onefile else "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--add-data", f"{ROOT / 'engine'}{sep}engine",
        "--add-data", f"{ROOT / 'assets'}{sep}assets",
        "--add-data", f"{ROOT / 'LICENSE'}{sep}.",
        "--add-data", f"{ROOT / 'THIRD_PARTY_NOTICES.md'}{sep}.",
        # the stronger AI runs this script in its own Python, so it ships as a plain file
        "--add-data", f"{ROOT / 'perfect_wallpaper' / 'creative_worker.py'}{sep}perfect_wallpaper",
        "--collect-all", "tkinterdnd2",
        "--collect-all", "pillow_heif",
        "--hidden-import", "ncnn",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / ("onefile" if onefile else "onedir")),
        "--specpath", str(ROOT / "build"),
    ])


def installer() -> Path:
    iscc = next((p for p in ISCC_PLACES if p.exists()), None) or shutil.which("ISCC")
    if not iscc:
        sys.exit("Inno Setup 6 is not installed, so the installer cannot be built (https://jrsoftware.org).")
    subprocess.run([str(iscc), f"/DAppVersion={__version__}", f"/O{ROOT / 'dist'}",
                    str(ROOT / "installer" / "PerfectWallpaper.iss")], check=True)
    return ROOT / "dist" / f"PerfectWallpaper-Setup-{__version__}.exe"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--installer", action="store_true")
    args = parser.parse_args()
    both = not (args.portable or args.installer)
    if not (ROOT / "engine" / "realesrgan-ncnn-vulkan.exe").exists():
        sys.exit("The engine is missing. Run: python scripts/get_engine.py")
    if both or args.portable:
        pyinstaller(onefile=True)
    if both or args.installer:
        pyinstaller(onefile=False)
        print(f"Installer: {installer()}")


if __name__ == "__main__":
    main()
