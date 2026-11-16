"""The JSON-lines protocol the Ex app drives.

Every command prints events to stdout, one JSON object per line, and always
ends with exactly one terminal event: ``listing``, ``done``, ``formats``,
``error`` or ``cancelled``. When a password is needed a ``password`` event is
printed and one JSON line is read from stdin: ``{"password": "..."}`` or
``{"cancel": true}``. A closed stdin counts as cancel. SIGTERM cancels and
cleans up.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .extract import Options, PasswordBook, extract, inspect
from .listing import list_archive
from .pack import PACK_FORMATS, PackOptions, available_formats, pack

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANCELLED = 130
PROGRESS_HEARTBEAT_SECONDS = 0.5


def emit(event: dict) -> None:
    # Names a tool could not decode arrive with lone surrogates; replace them
    # rather than lose the whole event.
    line = json.dumps(event, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8", "replace"))
    sys.stdout.flush()


def _read_reply() -> dict:
    line = sys.stdin.readline()
    if not line:
        return {}
    try:
        reply = json.loads(line)
    except ValueError:
        return {}
    return reply if isinstance(reply, dict) else {}


def ask_password(archive: Path, retry: bool) -> str | None:
    emit({"type": "password", "archive": archive.name, "retry": retry})
    password = _read_reply().get("password")
    return password if isinstance(password, str) and password else None


class ProgressEmitter:
    """Forwards progress only when it changes, plus a heartbeat while it does not."""

    def __init__(self) -> None:
        self._last: int | None = None
        self._sent_at = 0.0

    def __call__(self, percent: int | None) -> None:
        now = time.monotonic()
        if percent != self._last or now - self._sent_at >= PROGRESS_HEARTBEAT_SECONDS:
            self._last = percent
            self._sent_at = now
            emit({"type": "progress", "percent": percent})


def _list(args: argparse.Namespace) -> int:
    listing = list_archive(inspect(Path(args.archive)), PasswordBook(ask_password))
    if listing.error:
        emit({"type": "error", "message": listing.error})
        return EXIT_FAILED
    emit(
        {
            "type": "listing",
            "archive": str(listing.archive),
            "label": listing.label,
            "entries": [asdict(entry) for entry in listing.entries],
        }
    )
    return EXIT_OK


def _extract(args: argparse.Namespace) -> int:
    progress = ProgressEmitter()
    progress(None)
    options = Options(
        output_dir=Path(args.output).expanduser().absolute() if args.output else None,
        only=tuple(args.only or ()),
    )
    outcome = extract(inspect(Path(args.archive)), options, PasswordBook(ask_password), progress)
    if not outcome.ok:
        emit({"type": "error", "message": outcome.error})
        return EXIT_FAILED
    emit(
        {
            "type": "done",
            "outputs": [str(path) for path in outcome.outputs],
            "files": outcome.files,
            "bytes": outcome.total_bytes,
            "seconds": round(outcome.seconds, 3),
            "notes": list(outcome.notes),
        }
    )
    return EXIT_OK


def _pack(args: argparse.Namespace) -> int:
    password = _read_reply().get("password") if args.password_stdin else None
    progress = ProgressEmitter()
    progress(None)
    options = PackOptions(
        format=args.format,
        level=args.level,
        password=password or None,
        encrypt_names=args.encrypt_names,
        volume_bytes=args.volume_bytes,
    )
    outcome = pack([Path(p) for p in args.sources], Path(args.output).expanduser().absolute(), args.name, options, progress)
    if not outcome.ok:
        emit({"type": "error", "message": outcome.error})
        return EXIT_FAILED
    emit(
        {
            "type": "done",
            "outputs": [str(path) for path in outcome.outputs],
            "files": len(outcome.outputs),
            "bytes": outcome.total_bytes,
            "seconds": round(outcome.seconds, 3),
            "notes": [],
        }
    )
    return EXIT_OK


def _formats(_args: argparse.Namespace) -> int:
    emit({"type": "formats", "pack": list(available_formats())})
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ex-engine")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list")
    listing.add_argument("archive")
    listing.set_defaults(run=_list)

    extracting = commands.add_parser("extract")
    extracting.add_argument("archive")
    extracting.add_argument("--output")
    extracting.add_argument("--only", action="append")
    extracting.set_defaults(run=_extract)

    packing = commands.add_parser("pack")
    packing.add_argument("--format", required=True, choices=PACK_FORMATS)
    packing.add_argument("--name", required=True)
    packing.add_argument("--output", required=True)
    packing.add_argument("--level", type=int, default=5)
    packing.add_argument("--volume-bytes", type=int)
    packing.add_argument("--encrypt-names", action="store_true")
    packing.add_argument("--password-stdin", action="store_true")
    packing.add_argument("sources", nargs="+")
    packing.set_defaults(run=_pack)

    formats = commands.add_parser("formats")
    formats.set_defaults(run=_formats)
    return parser


def _cancel_on_terminate(_signum, _frame) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _cancel_on_terminate)
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except KeyboardInterrupt:
        emit({"type": "cancelled"})
        return EXIT_CANCELLED
    except Exception as exc:  # the app must always get a terminal event
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return EXIT_FAILED
