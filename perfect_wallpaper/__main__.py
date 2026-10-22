"""Start the app, or run the command line version when given options.

With no arguments, or with just a picture (as when a file is dropped onto the .exe or
chosen from the right click menu), the window opens. "--engine-server" starts the AI
helper process (the packaged .exe starts itself this way). Anything else goes to the
command line version.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--engine-server"]:
        from perfect_wallpaper.engine_server import main as serve

        serve(argv[1])
        return 0
    if not argv or (len(argv) == 1 and Path(argv[0]).is_file()):
        from perfect_wallpaper.app import main as run_app

        run_app(argv[0] if argv else None)
        return 0
    from perfect_wallpaper.cli import main as run_cli

    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
