"""What is inside an archive, without extracting it."""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .backends import SEARCH_PATH, helper_binary, resolve
from .extract import (
    DAMAGED,
    MAX_PASSWORD_PROMPTS,
    NOT_ARCHIVE,
    PASSWORD_NEEDED,
    PASSWORD_WRONG,
    Job,
    PasswordBook,
    _no_tool_message,
)
from .formats import zip_has_legacy_names
from .runner import RunResult, capture
from .stage import JUNK_NAMES

# Formats Python's tarfile reads natively, compressed or not. lzma.open
# also reads the legacy .lzma container, so "lzma" works through r:*.
_TARFILE_FORMATS = frozenset({"tar", "gzip", "bzip2", "xz", "zstd", "lzma"})
# Compressors only a helper binary decodes; their tar is read from its stdout.
_PIPED_FORMATS = frozenset({"lz4", "brotli", "lzip", "compress"})
_SEVENZIP_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_LSAR_TIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"
_LSAR_PASSWORD_FAILURE = "password"


@dataclass(frozen=True)
class Entry:
    path: str
    is_dir: bool
    size: int | None = None
    packed: int | None = None
    modified: float | None = None
    encrypted: bool = False


@dataclass(frozen=True)
class Listing:
    archive: Path
    label: str
    entries: tuple[Entry, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class _Read:
    entries: tuple[Entry, ...] | None
    needs_password: bool = False
    error: str = ""


def _readable(name: str) -> str:
    """A tar name ``tarfile`` could not decode as UTF-8, read as Latin-1 instead."""
    raw = name.encode("utf-8", "surrogateescape")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _clean_path(raw: str) -> str | None:
    """Normalise an entry path; None for entries that should stay hidden."""
    raw = _readable(raw)
    parts = [part for part in raw.replace("\\", "/").split("/") if part not in {"", "."}]
    if not parts or any(part.strip() in JUNK_NAMES or part.startswith("._") for part in parts):
        return None
    return "/".join(parts)


def _int(text: str | None) -> int | None:
    return int(text) if text and text.strip().isdigit() else None


def _sevenzip_time(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.split(".")[0], _SEVENZIP_TIME_FORMAT).timestamp()
    except ValueError:
        return None


def _parse_sevenzip(stdout: str, *, hide_streams: bool) -> tuple[Entry, ...]:
    entries: list[Entry] = []
    for block in stdout.split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" not in fields:
            continue
        path = _clean_path(fields["Path"])
        if path is None or (hide_streams and ":" in path):
            continue
        entries.append(
            Entry(
                path=path,
                is_dir=fields.get("Folder") == "+" or fields.get("Attributes", "").startswith("D"),
                size=_int(fields.get("Size")),
                packed=_int(fields.get("Packed Size")),
                modified=_sevenzip_time(fields.get("Modified")),
                encrypted=fields.get("Encrypted") == "+",
            )
        )
    return tuple(entries)


def _lsar_time(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, _LSAR_TIME_FORMAT).timestamp()
    except ValueError:
        return None


def _parse_lsar(stdout: str) -> tuple[Entry, ...] | None:
    try:
        contents = json.loads(stdout)["lsarContents"]
    except (ValueError, KeyError, TypeError):
        return None
    entries = []
    for item in contents:
        path = _clean_path(str(item.get("XADFileName", "")))
        if path is None:
            continue
        entries.append(
            Entry(
                path=path,
                is_dir=bool(item.get("XADIsDirectory")),
                size=item.get("XADFileSize"),
                packed=item.get("XADCompressedSize"),
                modified=_lsar_time(item.get("XADLastModificationDate")),
                encrypted=bool(item.get("XADIsEncrypted")),
            )
        )
    return tuple(entries)


def _tar_entries(members) -> tuple[Entry, ...]:
    entries = []
    for member in members:
        path = _clean_path(member.name)
        if path is not None:
            entries.append(
                Entry(path, member.isdir(), None if member.isdir() else member.size, None, float(member.mtime))
            )
    return tuple(entries)


def _read_tarfile(archive: Path) -> _Read:
    try:
        with tarfile.open(archive, "r:*") as opened:
            return _Read(_tar_entries(opened.getmembers()))
    except (tarfile.TarError, OSError, EOFError, ValueError):
        return _Read(None)


def _read_piped_tar(archive: Path, format_key: str) -> _Read:
    """List a tar inside a stream only a helper binary can decompress."""
    binary = helper_binary(format_key)
    if binary is None:
        return _Read(None)
    with subprocess.Popen(
        [binary, "-d", "-c", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    ) as process:
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as opened:
                entries = _tar_entries(opened)
        except (tarfile.TarError, OSError, EOFError, ValueError):
            process.kill()
            return _Read(None)
    return _Read(entries)


def _classify(result: RunResult, archive: Path) -> _Read:
    cleaned = result.without(str(archive), archive.name)
    if cleaned.needs_password:
        return _Read(None, needs_password=True)
    return _Read(None, error=DAMAGED if cleaned.is_corrupt else "")


def _read_sevenzip(binary: str, archive: Path, password: str | None, format_key: str | None) -> _Read:
    # No -tSplit here: left to itself 7-Zip joins a byte split and lists the
    # archive inside, which is what the user wants to browse.
    result, stdout = capture([binary, "l", "-slt", "-ba", f"-p{password or ''}", "--", str(archive)])
    entries = _parse_sevenzip(stdout, hide_streams=format_key == "dmg")
    if result.ok:
        return _Read(entries)
    return _classify(result, archive)


def _read_lsar(archive: Path, password: str | None) -> _Read:
    lsar = shutil.which("lsar", path=SEARCH_PATH)
    if lsar is None:
        return _Read(None)
    result, stdout = capture([lsar, "-j", "-p", password or "", "--", str(archive)])
    entries = _parse_lsar(stdout)
    if result.ok and entries is not None:
        return _Read(entries)
    if not result.ok and _LSAR_PASSWORD_FAILURE in result.without(str(archive), archive.name).output.lower():
        return _Read(None, needs_password=True)
    return _classify(result, archive)


def _readers(job: Job, password: str | None):
    """Ways to read ``job``, best first, as zero-argument callables."""
    if job.format_key in _TARFILE_FORMATS:
        yield lambda: _read_tarfile(job.archive)
    if job.format_key in _PIPED_FORMATS:
        yield lambda: _read_piped_tar(job.archive, job.format_key)
    sevenzip = next((r for r in resolve(job.format_key) if r.name == "7z"), None) or next(
        (r for r in resolve(None) if r.name == "7z"), None
    )
    lsar_first = job.format_key == "zip" and zip_has_legacy_names(job.archive)
    if lsar_first:
        yield lambda: _read_lsar(job.archive, password)
    if sevenzip is not None:
        yield lambda: _read_sevenzip(sevenzip.binary, job.archive, password, job.format_key)
    if not lsar_first:
        yield lambda: _read_lsar(job.archive, password)


def _read(job: Job, password: str | None) -> _Read:
    first_error = ""
    for reader in _readers(job, password):
        found = reader()
        if found.entries is not None or found.needs_password:
            return found
        first_error = first_error or found.error
    return _Read(None, error=first_error)


def list_archive(job: Job, book: PasswordBook) -> Listing:
    """The entries of ``job``, asking for a password only if the names are hidden."""
    if job.error:
        return Listing(job.archive, job.label, error=job.error)
    found = _read(job, book.known)
    prompts = 0
    while found.needs_password and prompts < MAX_PASSWORD_PROMPTS:
        answer = book.ask(job.archive, prompts > 0 or book.known is not None)
        if answer is None:
            return Listing(job.archive, job.label, error=PASSWORD_NEEDED)
        found = _read(job, answer)
        if found.entries is not None:
            book.known = answer
        prompts += 1
    if found.entries is not None:
        return Listing(job.archive, job.label, found.entries)
    if found.needs_password:
        return Listing(job.archive, job.label, error=PASSWORD_WRONG)
    if job.format_key is None:
        return Listing(job.archive, job.label, error=NOT_ARCHIVE)
    if not resolve(job.format_key) and not shutil.which("lsar", path=SEARCH_PATH):
        return Listing(job.archive, job.label, error=_no_tool_message(job.format_key))
    return Listing(job.archive, job.label, error=found.error or DAMAGED)
