"""Command line use, for scripts and batch jobs.

    python -m perfect_wallpaper picture.jpg --size 5120x1440 --fit blur --set
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, applog, fitting, pipeline, resources, screens, upscale, wallpaper

ROTATIONS = {"left": 90, "right": 270, "0": 0, "90": 90, "180": 180, "270": 270}


def _say(text: str, end: str = "\n") -> None:
    if sys.stdout:  # the windowed .exe has no console
        print(text, end=end, flush=True)


def _size(text: str, found: list[screens.Screen]) -> tuple[int, int]:
    if text == "screen":
        if not found:
            raise SystemExit('Could not detect a screen. Give a size such as "--size 1920x1080".')
        return found[0].size
    if text == "all":
        if not found:
            raise SystemExit('Could not detect any screens. Give a size such as "--size 1920x1080".')
        return screens.combined_size(found)
    try:
        w, h = (int(part) for part in text.lower().replace("×", "x").split("x"))
    except ValueError:
        raise SystemExit(f'"{text}" is not a size. Use a form like 5120x1440.') from None
    return w, h


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="perfect-wallpaper",
        description="Enlarge a picture with AI and fit it to your screen. Give a folder to do every picture in it.",
    )
    parser.add_argument("picture", help="the picture to turn into a wallpaper, or a folder of pictures")
    parser.add_argument("--size", default="screen",
                        help='screen size such as 5120x1440, "screen" for the main display (default), '
                             'or "all" for one picture spanning every display')
    parser.add_argument("--gap", type=int, default=0,
                        help='with --size all: the width in pixels of the frames between monitors')
    parser.add_argument("--fit", choices=list(fitting.MODES), default="fill",
                        help="fill crops to fill the screen; blur, mirror and bars show the whole picture")
    parser.add_argument("--zoom", type=float, default=1.0, help="fill only: above 1 keeps a smaller part")
    parser.add_argument("--rotate", choices=list(ROTATIONS), default="0",
                        help="turn the picture first: left, right, or degrees counterclockwise")
    parser.add_argument("--model", "--enhance", dest="model", default=upscale.DEFAULT_MODEL,
                        choices=list(pipeline.ENHANCERS) + list(upscale.ALIASES),
                        help="AI model: natural (default), clean, fast, art, or off")
    parser.add_argument("--detail", type=float, default=0.0, help="0 to 1: add back the source's fine texture")
    parser.add_argument("--grain", type=float, default=0.0, help="0 to 1: film grain")
    parser.add_argument("--brightness", type=float, default=0.0, help="-1 to 1")
    parser.add_argument("--contrast", type=float, default=0.0, help="-1 to 1")
    parser.add_argument("--dim-icons", action="store_true", help="darken the strip behind desktop icons")
    parser.add_argument("--stronger", type=float, default=0.0,
                        help="0 to 1: the stronger AI's strength, if it is installed (0 is off)")
    parser.add_argument("--focus", help="where fill mode centers, as x,y fractions such as 0.5,0.3")
    parser.add_argument("-o", "--output", help="where to save (a file, or a folder for a folder of pictures)")
    parser.add_argument("--set", action="store_true", help="set the result as your wallpaper")
    parser.add_argument("--slideshow", type=int, metavar="MINUTES",
                        help="for a folder: use the results as a Windows slideshow, changing every MINUTES")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    applog.setup()
    screens.enable_dpi_awareness()
    found = screens.list_screens()
    target = _size(args.size, found)
    span = args.size == "all"
    gap = args.gap if span else 0
    work_size = screens.span_size(found, gap) if gap else target
    focus = None
    if args.focus:
        try:
            focus = tuple(float(part) for part in args.focus.split(","))
            assert len(focus) == 2
        except (ValueError, AssertionError):
            raise SystemExit(f'"{args.focus}" is not a focus point. Use a form like 0.5,0.3.') from None

    settings = pipeline.Settings(
        target=work_size, mode=args.fit, rotation=ROTATIONS[args.rotate], focus=focus, enhance=args.model,
        zoom=args.zoom, detail=args.detail, grain=args.grain, brightness=args.brightness, contrast=args.contrast,
        dim_icons=args.dim_icons, creative=args.stronger)
    source = Path(args.picture)
    if source.is_dir():
        patterns = pipeline.PICTURE_PATTERNS.replace("*", "").split()
        pictures = sorted(p for p in source.iterdir() if p.suffix.lower() in patterns)
        out_dir = Path(args.output) if args.output else resources.output_dir() / f"{source.name} {target[0]}x{target[1]}"
        for path in pictures:
            _make(path, settings, pipeline.unique_path(out_dir / f"{path.stem}.png"), target, found, gap)
        _say(f"Made {len(pictures)} wallpapers in {out_dir}")
        if args.slideshow:
            wallpaper.set_slideshow(out_dir, args.slideshow, True, span)
            _say(f"Windows now shows them as a slideshow, changing every {args.slideshow} minutes.")
        return 0

    output = Path(args.output) if args.output else pipeline.unique_path(
        resources.output_dir() / f"{source.stem} {target[0]}x{target[1]}.png")
    if not _make(source, settings, output, target, found, gap):
        return 1
    if args.set:
        wallpaper.set_wallpaper(output, span=span)
        _say("Wallpaper set.")
    return 0


def _make(source: Path, settings, output: Path, target, found, gap) -> bool:
    picture = pipeline.load_picture(source)
    _say(f"{source.name}: {picture.shape[1]} x {picture.shape[0]} -> {target[0]} x {target[1]}, fit {settings.mode}")
    try:
        image, report = pipeline.render(picture, settings, progress=lambda p: _say(f"\r  {p:6.1%}", end=""))
    except upscale.Cancelled:
        return False
    if gap:
        image = screens.cut_gaps(image, found, gap)
    _say("")
    pipeline.save(image, output)
    how = f"with AI ({report.ai_passes} pass{'es' if report.ai_passes > 1 else ''})" if report.ai_passes else "without AI"
    _say(f"Enlarged {report.scale:.2f} times {how}. Saved {output}")
    if report.note:
        _say(report.note)
    return True
