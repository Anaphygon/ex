"""The private workspace an extraction happens in, and how it becomes the result."""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

STAGING_PREFIX = ".ex-"
TOKEN_BYTES = 6
FIRST_DUPLICATE_NUMBER = 2
MAX_DUPLICATES = 9999

# Filesystem and archiver bookkeeping; never something the user packed.
JUNK_NAMES = frozenset(
    {
        "__MACOSX",
        ".DS_Store",
        ".Trashes",
        ".fseventsd",
        ".journal",
        ".journal_info_block",
        ".HFS+ Private Directory Data",
        "[HFS+ Private Data]",
    }
)


def create(parent: Path) -> Path:
    """Make an empty hidden directory inside ``parent``.

    Living beside the final location keeps the last step a same-filesystem
    rename. ``mkdtemp`` is avoided because its 0700 mode would stick to the
    result whenever this directory itself becomes the output folder.
    """
    path = parent / f"{STAGING_PREFIX}{secrets.token_hex(TOKEN_BYTES)}"
    path.mkdir()
    return path


def discard(path: Path) -> None:
    """Delete ``path``, including any read-only directories an archive created.

    Best effort: this also runs while unwinding from a failure, where raising
    would replace the real error. ``reset`` notices if something survived.
    """
    for root, directories, _files in os.walk(path):
        for name in directories:
            child = os.path.join(root, name)
            if not os.path.islink(child):
                with contextlib.suppress(OSError):
                    os.chmod(child, 0o700)
    shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def _unlocked(directory: str | Path) -> Iterator[None]:
    """Give the owner full access to ``directory`` for the duration of the block."""
    mode = stat.S_IMODE(os.lstat(directory).st_mode)
    if mode & stat.S_IRWXU == stat.S_IRWXU:
        yield
        return
    os.chmod(directory, mode | stat.S_IRWXU)
    try:
        yield
    finally:
        os.chmod(directory, mode)


def move(source: Path, target: Path) -> None:
    """Rename ``source``; a directory changing parent must be writable to do so."""
    mode = source.lstat().st_mode
    is_locked = stat.S_ISDIR(mode) and not mode & stat.S_IWUSR
    if is_locked:
        os.chmod(source, stat.S_IMODE(mode) | stat.S_IWUSR)
    source.rename(target)
    if is_locked:
        os.chmod(target, stat.S_IMODE(mode))


def reset(path: Path) -> None:
    """Empty ``path`` so the next backend starts from nothing."""
    discard(path)
    path.mkdir()


def _is_junk(entry: Path) -> bool:
    return entry.name.strip() in JUNK_NAMES


def _delete(entry: Path) -> None:
    if entry.is_dir() and not entry.is_symlink():
        discard(entry)
    else:
        entry.unlink()


def remove_junk(staging: Path) -> None:
    """Drop bookkeeping at the top level and inside a lone top-level folder.

    It has to go before the result is named, or a stray ``__MACOSX`` makes a
    single-folder archive look like a pile of loose files. Deeper levels are
    left alone: nothing depends on them.
    """
    for entry in list(staging.iterdir()):
        if _is_junk(entry):
            _delete(entry)
    survivors = list(staging.iterdir())
    if len(survivors) == 1 and survivors[0].is_dir() and not survivors[0].is_symlink():
        with _unlocked(survivors[0]):
            for entry in list(survivors[0].iterdir()):
                if _is_junk(entry):
                    _delete(entry)


def _lone_entry(staging: Path) -> Path | None:
    """The entry that ``promote`` will move up by itself, if there is one."""
    entries = list(staging.iterdir())
    return entries[0] if len(entries) == 1 and not entries[0].name.startswith(".") else None


def _make_traversable(directory: str) -> None:
    mode = stat.S_IMODE(os.lstat(directory).st_mode)
    if mode & 0o500 != 0o500:
        os.chmod(directory, mode | 0o500)


def prune_escaping_symlinks(staging: Path) -> tuple[str, ...]:
    """Delete symlinks that resolve outside the final result; return their paths.

    The boundary is what ``promote`` will expose, not the workspace: inside a
    lone top folder, ``pkg/leak -> ../secret.txt`` stays in the workspace now
    but points at a neighbouring file once ``pkg`` moves up. A lone symlink is
    dropped outright for the same reason.

    Resolution uses the real filesystem rather than path arithmetic, and
    deletion waits until the end: ``a -> b/..`` where ``b -> ..`` looks
    harmless lexically and stops resolving once ``b`` is gone.
    """
    lone = _lone_entry(staging)
    if lone is not None and lone.is_symlink():
        lone.unlink()
        return (lone.name,)
    boundary = lone if lone is not None and lone.is_dir() else staging
    return tuple(os.path.relpath(path, staging) for path in _prune_under(staging, boundary))


def _prune_under(root: Path, boundary: Path) -> list[str]:
    """Delete symlinks under ``root`` resolving outside ``boundary``."""
    limit = os.path.realpath(boundary)
    escaping: list[str] = []
    for current, directories, files in os.walk(root):
        for name in (*directories, *files):
            path = os.path.join(current, name)
            if os.path.islink(path):
                resolved = os.path.realpath(path)
                if resolved != limit and not resolved.startswith(limit + os.sep):
                    escaping.append(path)
            elif name in directories:
                _make_traversable(path)
    for path in escaping:
        with _unlocked(os.path.dirname(path)):
            os.unlink(path)
    return escaping


class SelectionError(LookupError):
    """A selected path is unsafe or absent from what was extracted."""


def _selected_relpath(path: str) -> str:
    cleaned = path.strip("/")
    parts = cleaned.split("/")
    if not cleaned or any(part in {"", ".", ".."} for part in parts):
        raise SelectionError(path)
    return cleaned


def _through_symlink(staging: Path, relpath: str) -> bool:
    """True when a folder on the way to ``relpath`` is a symlink.

    Such a path resolves outside the workspace, and moving it would move the
    user's own file. The entry itself may be a link; that is handled apart.
    """
    current = staging
    for part in relpath.split("/")[:-1]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def release_selection(staging: Path, parent: Path, selection: tuple[str, ...]) -> tuple[tuple[Path, ...], int]:
    """Move each selected entry out of ``staging`` into ``parent`` by its own name.

    Returns the new paths and how many symlinks were dropped. Each item is its
    own boundary: a link that reached a sibling inside the archive would point
    into the user's folder once moved, and a selected link is dropped whole.
    Raises ``SelectionError`` before moving anything when an item is missing.
    """
    relpaths = [_selected_relpath(path) for path in selection]
    sources = [staging / relpath for relpath in relpaths]
    missing = [
        path
        for path, relpath, source in zip(selection, relpaths, sources)
        if _through_symlink(staging, relpath) or not os.path.lexists(source)
    ]
    if missing:
        raise SelectionError(", ".join(missing))
    released: list[Path] = []
    dropped = 0
    for source in sources:
        if not os.path.lexists(source):
            continue
        if source.is_symlink():
            with _unlocked(source.parent):
                source.unlink()
            dropped += 1
            continue
        if source.is_dir():
            dropped += len(_prune_under(source, source))
        target = unique_path(parent / source.name, keep_suffix=not source.is_dir())
        with _unlocked(source.parent):
            move(source, target)
        released.append(target)
    return tuple(released), dropped


def sole_file(staging: Path) -> Path | None:
    """The only entry in ``staging`` when that entry is a regular file."""
    entries = list(staging.iterdir())
    if len(entries) == 1 and entries[0].is_file() and not entries[0].is_symlink():
        return entries[0]
    return None


def measure(path: Path) -> tuple[int, int]:
    """File count and total size, not following symlinks."""
    if not path.is_dir() or path.is_symlink():
        return 1, path.lstat().st_size
    count = size = 0
    for current, directories, files in os.walk(path):
        symlinked_dirs = (d for d in directories if os.path.islink(os.path.join(current, d)))
        for name in (*files, *symlinked_dirs):
            count += 1
            size += os.lstat(os.path.join(current, name)).st_size
    return count, size


def unique_path(target: Path, *, keep_suffix: bool) -> Path:
    """``target``, or the first free ``name (2)`` variant of it."""
    if not os.path.lexists(target):
        return target
    stem, suffix = (target.stem, target.suffix) if keep_suffix else (target.name, "")
    for number in range(FIRST_DUPLICATE_NUMBER, MAX_DUPLICATES):
        candidate = target.with_name(f"{stem} ({number}){suffix}")
        if not os.path.lexists(candidate):
            return candidate
    raise FileExistsError(f"too many copies of {target.name}")


def promote(staging: Path, parent: Path, folder_name: str) -> Path:
    """Turn the finished workspace into the visible result; never overwrites.

    A lone entry moves up as itself, so an archive holding one folder does
    not end up as ``name/name/``. Several entries get a folder named after
    the archive, so they cannot spill across the destination. A lone hidden
    entry is wrapped too, or the result would be invisible in Finder.
    """
    only = _lone_entry(staging)
    if only is not None:
        is_folder = only.is_dir() and not only.is_symlink()
        target = unique_path(parent / only.name, keep_suffix=not is_folder)
        move(only, target)
        staging.rmdir()
        return target
    target = unique_path(parent / folder_name, keep_suffix=False)
    staging.rename(target)
    return target
