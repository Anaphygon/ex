"""Archive format detection by magic bytes, with extension as fallback."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

ISO_MAGIC_OFFSET = 32769
TAR_MAGIC_OFFSET = 257
PROBE_BYTES = ISO_MAGIC_OFFSET + 8


@dataclass(frozen=True)
class Format:
    """A recognised archive format.

    kind is ``container`` for multi-entry archives, ``stream`` for
    single-member compressors (``.gz``), and ``tar`` for tar itself.
    """

    key: str
    label: str
    exts: tuple[str, ...]
    magic: tuple[tuple[int, bytes], ...]
    kind: str = "container"


# Longest magic wins, so order within this table does not matter.
FORMATS: tuple[Format, ...] = (
    Format("zip", "zip", (".zip", ".zipx", ".jar", ".war", ".epub", ".apk", ".xpi", ".whl", ".ipa", ".crx", ".odt", ".ods", ".odp", ".docx", ".xlsx", ".pptx"),
           ((0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08"))),
    Format("7z", "7z", (".7z",), ((0, b"7z\xbc\xaf\x27\x1c"),)),
    Format("rar5", "rar5", (".rar", ".rev"), ((0, b"Rar!\x1a\x07\x01\x00"),)),
    Format("rar", "rar4", (".rar", ".rev"), ((0, b"Rar!\x1a\x07\x00"),)),
    Format("gzip", "gzip", (".gz", ".tgz", ".taz"), ((0, b"\x1f\x8b"),), "stream"),
    Format("bzip2", "bzip2", (".bz2", ".tbz", ".tbz2", ".tb2"), ((0, b"BZh"),), "stream"),
    Format("xz", "xz", (".xz", ".txz"), ((0, b"\xfd7zXZ\x00"),), "stream"),
    Format("lzma", "lzma", (".lzma", ".tlz"), ((0, b"\x5d\x00\x00"),), "stream"),
    Format("zstd", "zstd", (".zst", ".tzst", ".zstd"), ((0, b"\x28\xb5\x2f\xfd"),), "stream"),
    Format("lz4", "lz4", (".lz4", ".tlz4"), ((0, b"\x04\x22\x4d\x18"),), "stream"),
    Format("lzip", "lzip", (".lz",), ((0, b"LZIP"),), "stream"),
    Format("compress", "compress", (".z", ".taz"), ((0, b"\x1f\x9d"),), "stream"),
    Format("brotli", "brotli", (".br",), (), "stream"),
    Format("tar", "tar", (".tar",), ((TAR_MAGIC_OFFSET, b"ustar"),), "tar"),
    Format("cab", "cab", (".cab",), ((0, b"MSCF"),)),
    Format("iso", "iso", (".iso", ".img"), ((ISO_MAGIC_OFFSET, b"CD001"),)),
    Format("lzh", "lzh", (".lzh", ".lha"), ((2, b"-lh"), (2, b"-lz"))),
    Format("arj", "arj", (".arj",), ((0, b"\x60\xea"),)),
    Format("cpio", "cpio", (".cpio",), ((0, b"070707"), (0, b"070701"), (0, b"070702"), (0, b"\xc7\x71"))),
    Format("ar", "ar/deb", (".a", ".deb", ".ar", ".udeb"), ((0, b"!<arch>"),)),
    Format("rpm", "rpm", (".rpm",), ((0, b"\xed\xab\xee\xdb"),)),
    Format("xar", "xar/pkg", (".xar", ".pkg", ".xip"), ((0, b"xar!"),)),
    Format("wim", "wim", (".wim", ".swm", ".esd"), ((0, b"MSWIM\x00\x00\x00"),)),
    Format("squashfs", "squashfs", (".squashfs", ".sfs", ".snap"),
           ((0, b"hsqs"), (0, b"sqsh"))),
    Format("ole", "ole/msi", (".msi", ".msp", ".doc", ".xls", ".ppt"),
           ((0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),)),
    Format("chm", "chm", (".chm",), ((0, b"ITSF"),)),
    Format("dmg", "dmg", (".dmg", ".sparseimage"), ()),
    Format("vhd", "vhd/vhdx", (".vhd", ".vhdx"), ((0, b"vhdxfile"), (0, b"conectix"))),
    Format("zoo", "zoo", (".zoo",), ((20, b"\xdc\xa7\xc4\xfd"),)),
    Format("stuffit", "stuffit", (".sit", ".sitx"),
           ((0, b"StuffIt"), (0, b"SIT!"), (0, b"SITD"))),
    Format("arc", "arc", (".arc",), ()),
    Format("alz", "alz", (".alz",), ((0, b"ALZ\x01"),)),
    Format("exe", "sfx/exe", (".exe",), ((0, b"MZ"),)),
)

# A plain byte-for-byte split (x.zip.001); only the name reveals it.
SPLIT = Format("split", "split", (), ())

BY_KEY: dict[str, Format] = {f.key: f for f in (*FORMATS, SPLIT)}

UTF8_NAME_FLAG = 0x800

# Extensions that mean "there is a tar inside", so the stem drops both parts.
TAR_SHORTHAND_EXTS = frozenset(
    {".tgz", ".taz", ".tbz", ".tbz2", ".tb2", ".txz", ".tlz", ".tzst", ".tlz4"}
)

# What a directory scan picks up. Far narrower than what ``detect`` accepts:
# nobody running ``ex ~/Downloads`` wants their .docx and .dmg files unpacked.
SCAN_EXTS = frozenset(
    {
        ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz", ".tbz2",
        ".xz", ".txz", ".zst", ".tzst", ".lz4", ".lz", ".lzma", ".z", ".cab",
        ".lzh", ".lha", ".arj", ".sit", ".sitx", ".alz", ".zoo",
    }
)


def _ext_candidates(path: Path) -> list[Format]:
    name = path.name.lower()
    hits = [f for f in FORMATS for e in f.exts if name.endswith(e)]
    # Prefer the longest matching extension (".tar.gz" over ".gz" is handled
    # by stem logic, but ".sitx" over ".sit" matters here).
    return sorted(hits, key=lambda f: max(len(e) for e in f.exts if name.endswith(e)), reverse=True)


def read_probe(path: Path) -> bytes:
    """Read enough of the head of the file to test every known magic."""
    with path.open("rb") as handle:
        return handle.read(PROBE_BYTES)


def match_magic(probe: bytes) -> Format | None:
    """Return the format whose magic bytes match, longest magic first."""
    matches = [
        (len(sig), fmt)
        for fmt in FORMATS
        for offset, sig in fmt.magic
        if probe[offset : offset + len(sig)] == sig
    ]
    if not matches:
        return None
    return max(matches, key=lambda pair: pair[0])[1]


def detect(path: Path, probe: bytes | None = None) -> Format | None:
    """Identify ``path``; magic bytes decide, the extension only breaks ties."""
    if probe is None:
        probe = read_probe(path)
    by_magic = match_magic(probe)
    by_ext = _ext_candidates(path)
    if by_magic is None:
        return by_ext[0] if by_ext else None
    # A format with no magic of its own can open with anything: a UDBZ disk
    # image starts with a perfectly valid bzip2 header.
    if by_ext and not by_ext[0].magic:
        return by_ext[0]
    # "MZ" only says "Windows binary"; a self-extractor named .rar is a rar.
    if by_magic.key == "exe" and by_ext:
        return by_ext[0]
    return by_magic


def zip_has_legacy_names(path: Path) -> bool:
    """True when entry names are non-ASCII and not flagged as UTF-8.

    These are in a code page the zip does not record. Only ``unar`` guesses
    it correctly; 7-Zip silently writes mojibake and the rest refuse.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            return any(
                not info.flag_bits & UTF8_NAME_FLAG and not info.filename.isascii()
                for info in archive.infolist()
            )
    # ValueError covers UnicodeDecodeError from a UTF-8-flagged name that is not UTF-8.
    except (zipfile.BadZipFile, OSError, NotImplementedError, ValueError, EOFError):
        return False
