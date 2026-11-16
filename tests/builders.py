"""Archive fixtures that the real tools cannot be coaxed into producing."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

RAR4_MARKER = b"Rar!\x1a\x07\x00"
RAR4_END_BLOCK = bytes.fromhex("c43d7b00400700")
RAR4_STORE_METHOD = 0x30
UNIX_REGULAR_FILE = 0o100644


def store_zip(path: Path, raw_name: bytes, data: bytes, flags: int = 0) -> Path:
    """A one-entry stored zip whose name bytes are written verbatim."""
    crc = zlib.crc32(data)
    local = (
        struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, 0, 0, 0, crc, len(data), len(data), len(raw_name), 0)
        + raw_name
        + data
    )
    central = (
        struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50, 20, 20, flags, 0, 0, 0, crc, len(data), len(data), len(raw_name), 0, 0, 0, 0, 0, 0,
        )
        + raw_name
    )
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(local), 0)
    path.write_bytes(local + central + end)
    return path


def _rar4_block(body: bytes) -> bytes:
    return struct.pack("<H", zlib.crc32(body) & 0xFFFF) + body


def store_rar4(path: Path, name: str, data: bytes) -> Path:
    """A one-entry stored RAR4 archive; current ``rar`` can no longer write this format."""
    raw_name = name.encode()
    archive_head = _rar4_block(struct.pack("<BHHHI", 0x73, 0, 13, 0, 0))
    file_head = _rar4_block(
        struct.pack(
            "<BHHIIBIIBBHI",
            0x74, 0x8000, 32 + len(raw_name), len(data), len(data), 3, zlib.crc32(data),
            0x50210000, 20, RAR4_STORE_METHOD, len(raw_name), UNIX_REGULAR_FILE,
        )
        + raw_name
    )
    path.write_bytes(RAR4_MARKER + archive_head + file_head + data + RAR4_END_BLOCK)
    return path
