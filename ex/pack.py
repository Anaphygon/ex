"""Making archives: zip, 7z, rar, and tar with any common compressor."""

from __future__ import annotations

import os
import shutil
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from . import stage
from .backends import SEARCH_PATH
from .runner import RunResult, run

PACK_FORMATS: tuple[str, ...] = ("zip", "7z", "tar.gz", "tar.xz", "tar.zst", "tar", "rar")
TAR_MODES = {"tar": "w", "tar.gz": "w:gz", "tar.xz": "w:xz", "tar.zst": "w:zst"}
DEFAULT_LEVEL = 5
COPY_CHUNK = 1 << 20
PERCENT_DONE = 100
BYTES_PER_KIB = 1024

# The four levels the UI offers, translated per tool. 0 stores without
# compressing; zstd has no such level, so it gets its fastest instead.
_GZIP_LEVELS = {0: 0, 1: 1, 5: 6, 9: 9}
_XZ_PRESETS = {0: 0, 1: 1, 5: 6, 9: 9}
_ZSTD_LEVELS = {0: 1, 1: 1, 5: 3, 9: 19}
_RAR_LEVELS = {0: 0, 1: 1, 5: 3, 9: 5}

_PASSWORD_FORMATS = frozenset({"zip", "7z", "rar"})
_HIDDEN_NAME_FORMATS = frozenset({"7z", "rar"})
_VOLUME_FORMATS = frozenset({"zip", "7z", "rar"})

Tick = Callable[[int | None], None]


@dataclass(frozen=True)
class PackOptions:
    format: str
    level: int = DEFAULT_LEVEL
    password: str | None = None
    encrypt_names: bool = False
    volume_bytes: int | None = None


@dataclass(frozen=True)
class PackOutcome:
    seconds: float
    outputs: tuple[Path, ...] = ()
    total_bytes: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def available_formats() -> tuple[str, ...]:
    """Formats that can be written with the tools installed right now."""
    has_7z = shutil.which("7zz", path=SEARCH_PATH) or shutil.which("7z", path=SEARCH_PATH)
    has_rar = shutil.which("rar", path=SEARCH_PATH)
    return tuple(
        fmt
        for fmt in PACK_FORMATS
        if (fmt not in {"zip", "7z"} or has_7z) and (fmt != "rar" or has_rar)
    )


def _nearest_level(table: dict[int, int], level: int) -> int:
    return table[min(table, key=lambda key: abs(key - level))]


def _problem(sources: list[Path], name: str, options: PackOptions) -> str | None:
    if options.format not in PACK_FORMATS:
        return f"Unknown format: {options.format}"
    if options.format not in available_formats():
        return f"No tool for {options.format} is installed"
    if not name or "/" in name or name in {".", ".."}:
        return "Invalid archive name"
    if not sources:
        return "Nothing to compress"
    if missing := [str(path) for path in sources if not os.path.lexists(path)]:
        return f"Not found: {', '.join(missing)}"
    if options.password and options.format not in _PASSWORD_FORMATS:
        return f"{options.format} does not support passwords"
    if options.encrypt_names and options.format not in _HIDDEN_NAME_FORMATS:
        return f"{options.format} cannot hide file names"
    if options.volume_bytes and options.format not in _VOLUME_FORMATS:
        return f"{options.format} cannot be split into volumes"
    return None


def _volume_switch(volume_bytes: int | None) -> list[str]:
    return [f"-v{max(1, volume_bytes // BYTES_PER_KIB)}k"] if volume_bytes else []


def _sevenzip_argv(target: Path, sources: list[Path], options: PackOptions) -> list[str]:
    binary = shutil.which("7zz", path=SEARCH_PATH) or shutil.which("7z", path=SEARCH_PATH)
    is_zip = options.format == "zip"
    secrets = []
    if options.password:
        secrets = [f"-p{options.password}", "-mem=AES256" if is_zip else ""]
        if options.encrypt_names:
            secrets.append("-mhe=on")
    return [
        arg
        for arg in (
            binary, "a", "-y", "-bso1", "-bse1", "-bsp1", "-snl",
            f"-t{'zip' if is_zip else '7z'}", f"-mx={options.level}",
            "-xr!.DS_Store", "-xr!__MACOSX",
            *secrets, *_volume_switch(options.volume_bytes),
            "--", str(target), *map(str, sources),
        )
        if arg
    ]


def _rar_argv(target: Path, sources: list[Path], options: PackOptions) -> list[str]:
    secret = []
    if options.password:
        secret = [f"-hp{options.password}" if options.encrypt_names else f"-p{options.password}"]
    return [
        shutil.which("rar", path=SEARCH_PATH), "a", "-idq", "-r", "-ep1", "-ol",
        f"-m{_nearest_level(_RAR_LEVELS, options.level)}",
        "-x*.DS_Store", "-x*__MACOSX*",
        *secret, *_volume_switch(options.volume_bytes),
        "--", str(target), *map(str, sources),
    ]


def _run_tool(argv: list[str], on_tick: Tick | None) -> RunResult:
    return run(argv, progress_style="percent", on_tick=on_tick)


class _CountingReader:
    """Reports bytes read through to ``on_bytes`` while ``tarfile`` copies a file."""

    def __init__(self, handle: BinaryIO, on_bytes: Callable[[int], None]) -> None:
        self._handle = handle
        self._on_bytes = on_bytes

    def read(self, size: int = -1) -> bytes:
        data = self._handle.read(size)
        self._on_bytes(len(data))
        return data


def _walk(source: Path):
    """``source`` and everything under it, minus macOS bookkeeping."""
    yield source
    if source.is_dir() and not source.is_symlink():
        for current, directories, files in os.walk(source):
            directories[:] = sorted(d for d in directories if d not in stage.JUNK_NAMES)
            for name in (*directories, *sorted(f for f in files if f not in stage.JUNK_NAMES)):
                yield Path(current) / name


def _tar_open_kwargs(options: PackOptions) -> dict:
    if options.format == "tar.gz":
        return {"compresslevel": _nearest_level(_GZIP_LEVELS, options.level)}
    if options.format == "tar.xz":
        return {"preset": _nearest_level(_XZ_PRESETS, options.level)}
    if options.format == "tar.zst":
        return {"level": _nearest_level(_ZSTD_LEVELS, options.level)}
    return {}


def _write_tar(target: Path, sources: list[Path], options: PackOptions, on_tick: Tick | None) -> None:
    items = [(item, source.parent) for source in sources for item in _walk(source)]
    total = sum(item.lstat().st_size for item, _ in items if item.is_file() and not item.is_symlink()) or 1
    done = 0

    def advance(count: int) -> None:
        nonlocal done
        done += count
        if on_tick:
            on_tick(min(PERCENT_DONE, done * PERCENT_DONE // total))

    with tarfile.open(target, TAR_MODES[options.format], **_tar_open_kwargs(options)) as archive:
        for item, base in items:
            info = archive.gettarinfo(str(item), arcname=str(item.relative_to(base)))
            if info is None:  # sockets and other things tar cannot store
                continue
            if info.isreg():
                with item.open("rb") as handle:
                    archive.addfile(info, _CountingReader(handle, advance))
            else:
                archive.addfile(info)
    if on_tick:
        on_tick(PERCENT_DONE)


def _produce(target: Path, sources: list[Path], options: PackOptions, on_tick: Tick | None) -> str | None:
    if options.format in TAR_MODES:
        _write_tar(target, sources, options, on_tick)
        return None
    argv = _rar_argv(target, sources, options) if options.format == "rar" else _sevenzip_argv(target, sources, options)
    result = _run_tool(argv, on_tick)
    return None if result.ok else result.without(str(target)).first_error_line()


def _rename_set(produced: list[Path], name: str, base: str) -> list[str]:
    return [base + path.name[len(name):] for path in produced]


def _release(staging: Path, parent: Path, name: str) -> tuple[Path, ...]:
    """Move everything produced in ``staging`` out under the first free base name.

    A volume set is renamed as a whole, so ``x.7z.001`` never ends up next to
    a ``x (2).7z.002``.
    """
    produced = sorted(staging.iterdir())
    for number in range(1, stage.MAX_DUPLICATES):
        base = name if number == 1 else f"{name} ({number})"
        names = _rename_set(produced, name, base)
        if not any(os.path.lexists(parent / candidate) for candidate in names):
            for path, candidate in zip(produced, names):
                path.rename(parent / candidate)
            return tuple(parent / candidate for candidate in names)
    raise FileExistsError(f"too many copies of {name}")


def pack(
    sources: list[Path],
    parent: Path,
    name: str,
    options: PackOptions,
    on_tick: Tick | None = None,
) -> PackOutcome:
    """Pack ``sources`` into ``parent/name.<format>``; never overwrites.

    Each source is stored under its own name. The archive is written in a
    hidden workspace and only appears once complete.
    """
    started = time.monotonic()
    sources = [Path(os.path.abspath(path)) for path in sources]
    if problem := _problem(sources, name, options):
        return PackOutcome(time.monotonic() - started, error=problem)
    staging: Path | None = None
    try:
        parent.mkdir(parents=True, exist_ok=True)
        staging = stage.create(parent)
        if error := _produce(staging / f"{name}.{options.format}", sources, options, on_tick):
            return PackOutcome(time.monotonic() - started, error=error)
        outputs = _release(staging, parent, name)
        return PackOutcome(time.monotonic() - started, outputs, sum(p.stat().st_size for p in outputs))
    except (OSError, tarfile.TarError) as exc:
        return PackOutcome(time.monotonic() - started, error=getattr(exc, "strerror", None) or str(exc))
    finally:
        if staging is not None and staging.exists():
            stage.discard(staging)
