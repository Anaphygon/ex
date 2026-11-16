"""Command line entry point."""

from __future__ import annotations

import argparse
import signal
from pathlib import Path

from . import __version__
from .extract import Job, Options, Outcome, PasswordBook, extract, inspect
from .frontends import GuiFront, TerminalFront
from .volumes import is_later_volume, looks_like_archive

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ex",
        description="Extract any archive: zip, 7z, rar, tar, gz, iso, dmg, and many more.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="file",
        help="archives to extract, or a folder to scan for archives (default: this folder)",
    )
    parser.add_argument("-o", "--output", type=Path, metavar="DIR", help="extract into this folder")
    parser.add_argument("-p", "--password", help="archive password (asked for when needed if omitted)")
    parser.add_argument("--version", action="version", version=f"ex {__version__}")
    parser.add_argument("--gui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reveal", action="store_true", help=argparse.SUPPRESS)
    return parser


def _scan(directory: Path) -> list[Path]:
    return sorted(
        entry
        for entry in directory.iterdir()
        if entry.is_file() and looks_like_archive(entry) and not is_later_volume(entry)
    )


def _collect_targets(paths: list[Path], front) -> list[Path]:
    """Named files are taken at face value; folders are scanned and confirmed."""
    named = [path for path in paths if not path.is_dir()]
    scanned = [archive for path in paths if path.is_dir() for archive in _scan(path)]
    if not named and not scanned:
        front.nothing_to_do()
    if scanned and not front.confirm(scanned):
        return named
    return [*named, *scanned]


def _unique_jobs(targets: list[Path]) -> list[Job]:
    """Selecting every part of a split archive must extract it only once."""
    jobs: dict[Path, Job] = {}
    for target in targets:
        job = inspect(target)
        jobs.setdefault(job.archive, job)
    return list(jobs.values())


def _interrupt_on_terminate(_signum, _frame) -> None:
    # Cancelling a Quick Action sends SIGTERM; treat it like Ctrl-C so the
    # child is stopped and the hidden workspace gets cleaned up.
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _interrupt_on_terminate)
    args = build_parser().parse_args(argv)
    front = GuiFront(reveal=args.reveal) if args.gui else TerminalFront()
    try:
        targets = _collect_targets(args.paths or [Path.cwd()], front)
        if not targets:
            return EXIT_OK
        book = PasswordBook(front.ask_password, args.password)
        options = Options(output_dir=args.output.expanduser().absolute() if args.output else None)
        outcomes: list[Outcome] = []
        for job in _unique_jobs(targets):
            front.begin(job)
            outcome = extract(job, options, book, front.tick)
            front.finish(outcome)
            outcomes.append(outcome)
        front.summarize(outcomes)
    except KeyboardInterrupt:
        front.cancelled()
        return EXIT_INTERRUPTED
    except Exception as exc:
        # Finder runs discard stdout and stderr, so a traceback would just vanish.
        front.fatal(f"{type(exc).__name__}: {exc}")
        return EXIT_FAILED
    return EXIT_OK if all(outcome.ok for outcome in outcomes) else EXIT_FAILED
