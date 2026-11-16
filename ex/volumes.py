"""Multi-volume archives and clean base names.

Users drag whatever part their eye lands on. Every extractor wants the
*first* volume, so normalise to it before doing anything else.
"""

from __future__ import annotations

import re
from pathlib import Path

from .formats import FORMATS, SCAN_EXTS, TAR_SHORTHAND_EXTS

# archive.7z.001 / archive.zip.002 - numbered suffix after a real extension.
_NUMBERED = re.compile(r"^(?P<base>.+\.[A-Za-z0-9]{1,5})\.(?P<num>\d{3})$")
# archive.part3.rar / archive.part003.rar
_RAR_PART = re.compile(r"^(?P<base>.+)\.part(?P<num>\d+)\.rar$", re.IGNORECASE)
# archive.r00 ... archive.r99 (old rar scheme, archive.rar is the first)
_RAR_OLD = re.compile(r"^(?P<base>.+)\.r(?P<num>\d{2,3})$", re.IGNORECASE)
# archive.z01 ... (split zip, archive.zip is the first)
_ZIP_SPLIT = re.compile(r"^(?P<base>.+)\.z(?P<num>\d{2,3})$", re.IGNORECASE)

_ARCHIVE_EXTS = frozenset(e for f in FORMATS for e in f.exts) | TAR_SHORTHAND_EXTS


def first_volume(path: Path) -> Path:
    """Map any volume of a split archive to its first volume.

    Returns ``path`` unchanged when it is not part of a set, or when the
    computed first volume does not exist on disk.
    """
    name = path.name
    candidates: list[str] = []

    if match := _RAR_PART.match(name):
        width = len(match.group("num"))
        candidates.append(f"{match.group('base')}.part{1:0{width}d}.rar")
    elif match := _NUMBERED.match(name):
        width = len(match.group("num"))
        candidates.append(f"{match.group('base')}.{1:0{width}d}")
    elif match := _RAR_OLD.match(name):
        candidates.append(f"{match.group('base')}.rar")
    elif match := _ZIP_SPLIT.match(name):
        candidates.append(f"{match.group('base')}.zip")

    for candidate in candidates:
        if resolved := _stored_entry(path.parent, candidate):
            return resolved
    return path


def _stored_entry(directory: Path, name: str) -> Path | None:
    """The entry called ``name``, spelled as it is on disk.

    A plain ``exists()`` also says yes to the wrong case on APFS, and then
    ``X.PART1.RAR`` and ``X.part1.rar`` look like two different archives.
    """
    if not directory.is_dir():
        return None
    wanted = name.lower()
    return next((entry for entry in directory.iterdir() if entry.name.lower() == wanted), None)


def is_later_volume(path: Path) -> bool:
    """True when ``path`` belongs to a split set but is not its first volume."""
    return first_volume(path) != path


def is_numbered_split(path: Path) -> bool:
    """True for ``x.zip.001`` style byte splits.

    ``.7z.001`` is excluded because 7-Zip reads its own volumes natively.
    Everything else has to be joined first: given ``x.zip.001`` directly,
    extractors just read the first piece and report a damaged archive.
    """
    match = _NUMBERED.match(path.name)
    return match is not None and not match.group("base").lower().endswith(".7z")


def missing_split_part(path: Path) -> int | None:
    """The first absent number in a ``.001`` set, or None when there is no gap.

    A missing *last* part cannot be seen from names alone; opening the joined
    archive catches that one.
    """
    match = _NUMBERED.match(path.name)
    if match is None:
        return None
    base = match.group("base").lower()
    present = {
        int(found.group("num"))
        for entry in path.parent.iterdir()
        if (found := _NUMBERED.match(entry.name)) and found.group("base").lower() == base
    }
    return next((number for number in range(1, max(present, default=0) + 1) if number not in present), None)


def has_zip_segments(path: Path) -> bool:
    """True for the ``.zip`` of a ``.z01``-style segmented set."""
    return path.suffix.lower() == ".zip" and (
        path.with_suffix(".z01").exists() or path.with_suffix(".Z01").exists()
    )


def looks_like_archive(path: Path) -> bool:
    """True when a directory scan should offer this file."""
    name = path.name.lower()
    if match := _NUMBERED.match(name):
        name = match.group("base")
    return any(name.endswith(ext) for ext in SCAN_EXTS)


def archive_stem(path: Path) -> str:
    """The name to give the extracted result.

    ``x.tar.gz`` -> ``x``, ``x.part1.rar`` -> ``x``, ``x.7z.001`` -> ``x``.
    """
    name = path.name
    if match := _RAR_PART.match(name):
        return match.group("base")
    if match := _NUMBERED.match(name):
        name = match.group("base")
    elif match := _RAR_OLD.match(name):
        return match.group("base")
    elif match := _ZIP_SPLIT.match(name):
        return match.group("base")

    lowered = name.lower()
    for ext in sorted(_ARCHIVE_EXTS, key=len, reverse=True):
        if lowered.endswith(ext) and len(lowered) > len(ext):
            name = name[: -len(ext)]
            lowered = name.lower()
            break

    if lowered.endswith(".tar") and len(lowered) > len(".tar"):
        name = name[: -len(".tar")]
    return name or path.name
