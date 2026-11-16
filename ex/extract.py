"""One archive in, one tidy result out."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import macos, stage
from .backends import ResolvedBackend, extract_argv, missing_binaries, resolve
from .formats import BY_KEY, SPLIT, detect, zip_has_legacy_names
from .runner import RunResult, run
from .volumes import (
    archive_stem,
    first_volume,
    has_zip_segments,
    is_numbered_split,
    looks_like_archive,
    missing_split_part,
)

MAX_PASSWORD_PROMPTS = 3
MAX_PEEL_LAYERS = 3
SEVENZIP_WARNING_EXIT = 1
UNKNOWN_LABEL = "?"

NOT_FOUND = "File not found"
IS_DIRECTORY = "This is a folder, not an archive"
NOT_ARCHIVE = "Not an archive, or an unknown format"
EMPTY = "The archive is empty"
DAMAGED = "The archive is damaged or incomplete"
PASSWORD_WRONG = "Wrong password"
PASSWORD_NEEDED = "This archive needs a password"
QUARANTINE_FAILED = "could not copy the macOS quarantine flag"
NOT_IN_ARCHIVE = "Not in the archive"

Tick = Callable[[int | None], None]


@dataclass(frozen=True)
class Options:
    output_dir: Path | None = None
    # Archive paths to extract by themselves, each landing in output_dir under
    # its own name. Empty means the whole archive, tidied as one result.
    only: tuple[str, ...] = ()


@dataclass
class PasswordBook:
    """Asks for passwords and remembers the last one that worked.

    Archives extracted together usually share a source and a password, so a
    batch should only have to ask once.
    """

    ask: Callable[[Path, bool], str | None]
    known: str | None = None


@dataclass(frozen=True)
class Job:
    archive: Path
    format_key: str | None
    label: str
    size: int
    error: str | None = None


@dataclass(frozen=True)
class Outcome:
    archive: Path
    label: str
    seconds: float
    outputs: tuple[Path, ...] = ()
    files: int = 0
    total_bytes: int = 0
    error: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def output(self) -> Path | None:
        return self.outputs[0] if self.outputs else None


@dataclass(frozen=True)
class _Attempt:
    extracted: bool
    needs_password: bool = False
    error: str = ""


def inspect(path: Path) -> Job:
    """Work out what ``path`` is, without touching anything."""
    absolute = Path(os.path.abspath(path.expanduser()))
    if absolute.is_dir():
        return Job(absolute, None, UNKNOWN_LABEL, 0, error=IS_DIRECTORY)
    archive = first_volume(absolute)
    if not archive.is_file():
        return Job(archive, None, UNKNOWN_LABEL, 0, error=NOT_FOUND)
    try:
        size = archive.stat().st_size
        if is_numbered_split(archive):
            gap = missing_split_part(archive)
            error = None if gap is None else f"Part .{gap:03d} is missing"
            return Job(archive, SPLIT.key, SPLIT.label, size, error=error)
        found = detect(archive)
    except OSError as exc:
        return Job(archive, None, UNKNOWN_LABEL, 0, error=exc.strerror or str(exc))
    return Job(archive, found.key if found else None, found.label if found else UNKNOWN_LABEL, size)


def _preferred_backends(archive: Path, format_key: str | None) -> tuple[str, ...]:
    if format_key != "zip":
        return ()
    if has_zip_segments(archive):
        return ("7z",)
    return ("unar",) if zip_has_legacy_names(archive) else ()


def _succeeded(candidate: ResolvedBackend, result: RunResult, dest: Path) -> bool:
    if not any(dest.iterdir()):
        return False
    return result.ok or (candidate.name == "7z" and result.code == SEVENZIP_WARNING_EXIT)


def _no_tool_message(format_key: str | None) -> str:
    return f"No tool for this format is installed: {', '.join(missing_binaries(format_key))}"


def _error_text(result: RunResult, format_key: str | None) -> str:
    if result.ok:
        return EMPTY
    if format_key is None:
        return NOT_ARCHIVE
    if result.looks_damaged:
        return DAMAGED
    return result.first_error_line()


def _try_backends(
    archive: Path,
    format_key: str | None,
    dest: Path,
    password: str | None,
    on_tick: Tick | None,
    *,
    want_password: bool,
    prefer: tuple[str, ...],
    only: tuple[str, ...],
) -> _Attempt:
    candidates = resolve(format_key, want_password=want_password, prefer=prefer)
    if not candidates:
        return _Attempt(False, error=_no_tool_message(format_key))
    first_error = ""
    for candidate in candidates:
        stage.reset(dest)
        result = run(
            extract_argv(candidate, archive, dest, password, format_key, only),
            progress_style=candidate.backend.progress,
            on_tick=on_tick,
        ).without(str(dest), str(archive), archive.name)
        if result.needs_password:
            return _Attempt(False, needs_password=True)
        if _succeeded(candidate, result, dest):
            return _Attempt(True)
        if result.is_corrupt:
            return _Attempt(False, error=DAMAGED)
        first_error = first_error or _error_text(result, format_key)
    return _Attempt(False, error=first_error)


def _extract_with_passwords(
    archive: Path,
    format_key: str | None,
    dest: Path,
    book: PasswordBook,
    on_tick: Tick | None,
    only: tuple[str, ...] = (),
) -> _Attempt:
    prefer = _preferred_backends(archive, format_key)
    attempt = _try_backends(
        archive, format_key, dest, book.known, on_tick, want_password=False, prefer=prefer, only=only
    )
    prompts = 0
    while attempt.needs_password and prompts < MAX_PASSWORD_PROMPTS:
        answer = book.ask(archive, prompts > 0 or book.known is not None)
        if answer is None:
            return _Attempt(False, error=PASSWORD_NEEDED)
        attempt = _try_backends(
            archive, format_key, dest, answer, on_tick, want_password=True, prefer=prefer, only=only
        )
        if attempt.extracted:
            book.known = answer
        prompts += 1
    return _Attempt(False, error=PASSWORD_WRONG) if attempt.needs_password else attempt


def _peel(staging: Path, book: PasswordBook, on_tick: Tick | None, *, was_split: bool) -> str | None:
    """Open a lone wrapper left in ``staging``; return an error if one is fatal.

    A lone tar is always a wrapper (x.tar.7z, x.tar.zst). After a byte split
    the joined file is the real archive, so failing to open it means parts
    are missing or damaged, and handing back a half-joined file would hide
    that. Anything else alone in an archive, like one .gz log in a zip, is
    what the user packed and stays as it is.
    """
    for layer in range(MAX_PEEL_LAYERS):
        inner = stage.sole_file(staging)
        if inner is None:
            return None
        found = detect(inner)
        must_open = was_split and layer == 0 and looks_like_archive(inner)
        if found is None or not (must_open or found.kind == "tar"):
            return None
        holding = stage.create(staging)
        attempt = _extract_with_passwords(inner, found.key, holding, book, on_tick)
        if not attempt.extracted:
            stage.discard(holding)
            return attempt.error if must_open else None
        inner.unlink()
        for child in list(holding.iterdir()):
            stage.move(child, staging / child.name)
        holding.rmdir()
    return None


def _narrowing(job: Job, options: Options) -> tuple[str, ...]:
    """Selected names a backend may be told about.

    A compressed stream's members are inside the tar it wraps, so naming them
    to the tool that opens the outer layer would match nothing.
    """
    if not options.only or _selection_needs_peeling(job):
        return ()
    return options.only


def _selection_needs_peeling(job: Job) -> bool:
    """True when listed paths live inside a wrapper the first pass leaves behind.

    The listing looks through compressed streams (x.tar.lz4) and byte splits
    (x.zip.001), so those must be unwrapped before a selection can be found.
    Anywhere else a selected lone tar is just a file the user picked.
    """
    found = BY_KEY.get(job.format_key)
    return found is not None and (found.kind == "stream" or found.key == SPLIT.key)


def _failed(job: Job, error: str, started: float) -> Outcome:
    return Outcome(job.archive, job.label, time.monotonic() - started, error=error)


def extract(job: Job, options: Options, book: PasswordBook, on_tick: Tick | None = None) -> Outcome:
    """Extract ``job`` beside its archive. The archive itself is never touched.

    Everything happens in a hidden workspace that only becomes visible once
    complete, so failures and interrupts leave nothing half-done.
    """
    started = time.monotonic()
    if job.error:
        return _failed(job, job.error, started)
    parent = options.output_dir or job.archive.parent
    staging: Path | None = None
    try:
        parent.mkdir(parents=True, exist_ok=True)
        staging = stage.create(parent)
        attempt = _extract_with_passwords(
            job.archive, job.format_key, staging, book, on_tick, _narrowing(job, options)
        )
        if not attempt.extracted:
            return _failed(job, attempt.error, started)
        stage.remove_junk(staging)
        if not options.only or _selection_needs_peeling(job):
            if error := _peel(staging, book, on_tick, was_split=job.format_key == SPLIT.key):
                return _failed(job, error, started)
        stage.remove_junk(staging)
        if options.only:
            outputs, dropped = stage.release_selection(staging, parent, options.only)
        else:
            dropped = len(stage.prune_escaping_symlinks(staging))
            if not any(staging.iterdir()):
                return _failed(job, EMPTY, started)
            outputs = (stage.promote(staging, parent, archive_stem(job.archive)),)
        notes = tuple(note for output in outputs for note in _carry_quarantine(job.archive, output))
        if dropped:
            notes = (*notes, f"removed {dropped} symlink(s) pointing outside the archive")
        measured = [stage.measure(output) for output in outputs]
        return Outcome(
            job.archive,
            job.label,
            time.monotonic() - started,
            outputs,
            sum(count for count, _ in measured),
            sum(size for _, size in measured),
            notes=tuple(dict.fromkeys(notes)),
        )
    except stage.SelectionError as exc:
        return _failed(job, f"{NOT_IN_ARCHIVE}: {exc}", started)
    except OSError as exc:
        return _failed(job, exc.strerror or str(exc), started)
    finally:
        if staging is not None and staging.exists():
            stage.discard(staging)


def _carry_quarantine(archive: Path, output: Path) -> tuple[str, ...]:
    value = macos.read_quarantine(archive)
    if value is None or macos.apply_quarantine(output, value):
        return ()
    return (QUARANTINE_FAILED,)
