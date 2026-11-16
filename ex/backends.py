"""Extractor backends and the order we prefer them in, per format.

Every backend writes into a destination directory we own, so a failed
attempt is always discardable and the next candidate can try the same
archive.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .formats import SPLIT
from .volumes import archive_stem

PROGRESS_PERCENT = "percent"
PROGRESS_NONE = "none"

# Finder starts Quick Actions with a PATH that does not include Homebrew.
_EXTRA_PATH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
SEARCH_PATH = os.pathsep.join(
    dict.fromkeys(entry for entry in (*os.environ.get("PATH", "").split(os.pathsep), *_EXTRA_PATH_DIRS) if entry)
)


@dataclass(frozen=True)
class Backend:
    name: str
    binaries: tuple[str, ...] = ()
    supports_password: bool = False
    progress: str = PROGRESS_NONE


@dataclass(frozen=True)
class ResolvedBackend:
    """A backend plus the absolute path of the binary that was found."""

    backend: Backend
    binary: str

    @property
    def name(self) -> str:
        return self.backend.name


SEVENZIP = Backend("7z", ("7zz", "7z", "7za"), supports_password=True, progress=PROGRESS_PERCENT)
BSDTAR = Backend("bsdtar", ("bsdtar", "tar"))
UNAR = Backend("unar", ("unar",), supports_password=True)
UNRAR = Backend("unrar", ("unrar",), supports_password=True)
# Single-purpose decompressors; which binary depends on the format.
HELPER = Backend("helper")

BACKENDS: tuple[Backend, ...] = (SEVENZIP, BSDTAR, UNAR, UNRAR, HELPER)
BY_NAME: dict[str, Backend] = {b.name: b for b in BACKENDS}

_HELPER_BINARIES: dict[str, tuple[str, ...]] = {
    "lz4": ("lz4",),
    "brotli": ("brotli",),
    "lzip": ("lzip", "plzip"),
    "compress": ("gzip",),
}

# bsdtar goes first for compressors because it unpacks x.tar.gz in one pass;
# on a plain x.gz it refuses immediately and the next backend takes over.
PREFERENCE: dict[str, tuple[str, ...]] = {
    "zip": ("7z", "unar", "bsdtar"),
    "7z": ("7z", "unar", "bsdtar"),
    "rar": ("unrar", "unar", "7z"),
    "rar5": ("unrar", "unar", "7z"),
    "tar": ("bsdtar", "7z", "unar"),
    "gzip": ("bsdtar", "7z", "unar"),
    "bzip2": ("bsdtar", "7z", "unar"),
    "xz": ("bsdtar", "7z", "unar"),
    "lzma": ("bsdtar", "7z", "unar"),
    "zstd": ("bsdtar", "7z"),
    "lz4": ("helper", "bsdtar"),
    "brotli": ("helper",),
    "lzip": ("bsdtar", "helper"),
    "compress": ("bsdtar", "7z", "helper", "unar"),
    "cab": ("7z", "unar", "bsdtar"),
    "iso": ("7z", "bsdtar", "unar"),
    "lzh": ("unar", "7z"),
    "arj": ("unar", "7z"),
    "cpio": ("bsdtar", "7z", "unar"),
    "ar": ("bsdtar", "7z"),
    "rpm": ("7z", "bsdtar"),
    "xar": ("bsdtar", "7z"),
    "wim": ("7z",),
    "squashfs": ("7z",),
    "ole": ("7z",),
    "chm": ("7z", "unar"),
    "dmg": ("7z",),
    "vhd": ("7z",),
    "zoo": ("unar",),
    "stuffit": ("unar",),
    "arc": ("unar",),
    "alz": ("unar",),
    "exe": ("7z", "unar"),
    SPLIT.key: ("7z",),
}

# The table above only routes; between them 7-Zip and unar read far more than
# it lists, so an unidentified file still gets a chance.
UNKNOWN_ORDER: tuple[str, ...] = ("7z", "unar")


def _candidates(backend: Backend, format_key: str | None) -> tuple[str, ...]:
    return _HELPER_BINARIES.get(format_key, ()) if backend is HELPER else backend.binaries


def _find_binary(backend: Backend, format_key: str | None) -> str | None:
    for candidate in _candidates(backend, format_key):
        if found := shutil.which(candidate, path=SEARCH_PATH):
            return found
    return None


def helper_binary(format_key: str) -> str | None:
    """The single-purpose decompressor for ``format_key``, if installed."""
    return _find_binary(HELPER, format_key)


def _order(format_key: str | None) -> tuple[str, ...]:
    return PREFERENCE.get(format_key, UNKNOWN_ORDER)


def resolve(
    format_key: str | None,
    *,
    want_password: bool = False,
    prefer: tuple[str, ...] = (),
) -> list[ResolvedBackend]:
    """Installed backends for ``format_key``, best first.

    ``prefer`` moves named backends to the front. With ``want_password``,
    backends that cannot take a password are dropped; they would only fail
    with a confusing error.
    """
    resolved: list[ResolvedBackend] = []
    for name in dict.fromkeys((*prefer, *_order(format_key))):
        backend = BY_NAME[name]
        if want_password and not backend.supports_password:
            continue
        if binary := _find_binary(backend, format_key):
            resolved.append(ResolvedBackend(backend, binary))
    return resolved


def missing_binaries(format_key: str | None) -> tuple[str, ...]:
    """What could be installed to handle this format."""
    wanted = (_candidates(BY_NAME[name], format_key) for name in _order(format_key))
    return tuple(dict.fromkeys(names[0] for names in wanted if names))


_GLOB_CHARACTERS = frozenset("*?[]\\")


def extract_argv(
    resolved: ResolvedBackend,
    archive: Path,
    dest: Path,
    password: str | None,
    format_key: str | None,
    only: tuple[str, ...] = (),
) -> list[str]:
    """Command line that extracts ``archive`` into the existing dir ``dest``.

    Without a password every tool is told not to prompt: an encrypted archive
    has to fail fast so we can ask in our own UI.

    ``only`` narrows the work to those entries where a tool can do so
    literally. Elsewhere everything is extracted and the caller picks the
    selection out afterwards, so it is a speed-up, never a filter to rely on.
    """
    binary, name = resolved.binary, resolved.name
    if name == "7z":
        # -sns- skips alternate streams, which 7-Zip would otherwise write as
        # literal "file:com.apple.provenance" files when reading disk images.
        # -spd makes the selected names literal instead of wildcards.
        forced = ["-tSplit"] if format_key == SPLIT.key else []
        narrowed = ["-spd"] if only else []
        return [
            binary, "x", "-y", "-sns-", "-bso1", "-bse1", "-bsp1", *forced, *narrowed,
            f"-p{password or ''}", f"-o{dest}", "--", str(archive), *only,
        ]
    if name == "bsdtar":
        literal = only if not any(_GLOB_CHARACTERS & set(path) for path in only) else ()
        return [binary, "-x", "-f", str(archive), "-C", str(dest), *literal]
    if name == "unar":
        return [
            binary, "-quiet", "-force-overwrite", "-no-directory",
            "-password", password or "", "-output-directory", str(dest), str(archive),
        ]
    if name == "unrar":
        return [binary, "x", "-y", "-idq", f"-p{password or '-'}", "--", str(archive), f"{dest}/"]
    if name == "helper":
        target = dest / archive_stem(archive)
        return ["/bin/sh", "-c", 'exec "$0" -d -c "$1" > "$2"', binary, str(archive), str(target)]
    raise ValueError(f"unknown backend: {name}")
