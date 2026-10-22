"""Entry point for the packaged .exe (PyInstaller needs a script outside the package)."""

import sys

from perfect_wallpaper.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
