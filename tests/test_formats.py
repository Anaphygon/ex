import zipfile

import pytest

from ex.formats import ISO_MAGIC_OFFSET, TAR_MAGIC_OFFSET, detect, zip_has_legacy_names
from tests.builders import store_zip


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return path


@pytest.mark.parametrize(
    "head,expected",
    [
        (b"PK\x03\x04rest", "zip"),
        (b"7z\xbc\xaf\x27\x1c", "7z"),
        (b"Rar!\x1a\x07\x01\x00", "rar5"),
        (b"Rar!\x1a\x07\x00", "rar"),
        (b"\x1f\x8b\x08", "gzip"),
        (b"BZh91AY", "bzip2"),
        (b"\xfd7zXZ\x00", "xz"),
        (b"\x28\xb5\x2f\xfd", "zstd"),
        (b"\x04\x22\x4d\x18", "lz4"),
        (b"LZIP", "lzip"),
        (b"\x1f\x9d", "compress"),
        (b"MSCF", "cab"),
        (b"xar!", "xar"),
        (b"!<arch>\n", "ar"),
    ],
)
def test_magic_decides_even_with_a_misleading_name(tmp_path, head, expected):
    assert detect(write(tmp_path, "renamed.bin", head + b"\0" * 64)).key == expected


def test_detects_tar_by_ustar_magic(tmp_path):
    assert detect(write(tmp_path, "x.bin", b"\0" * TAR_MAGIC_OFFSET + b"ustar\0" + b"\0" * 64)).key == "tar"


def test_detects_iso_by_volume_descriptor(tmp_path):
    assert detect(write(tmp_path, "x.bin", b"\0" * ISO_MAGIC_OFFSET + b"CD001" + b"\0" * 8)).key == "iso"


def test_extension_is_the_fallback_when_there_is_no_magic(tmp_path):
    assert detect(write(tmp_path, "x.7z", b"not really")).key == "7z"


def test_formats_without_magic_trust_the_extension_over_inner_compression(tmp_path):
    # A UDBZ disk image starts with a bzip2 header but must stay a dmg.
    assert detect(write(tmp_path, "installer.dmg", b"BZh91AY" + b"\0" * 64)).key == "dmg"


def test_self_extracting_rar_keeps_its_rar_routing(tmp_path):
    assert detect(write(tmp_path, "setup.rar", b"MZ" + b"\0" * 64)).key in {"rar", "rar5"}


def test_bare_executable_is_reported_as_exe(tmp_path):
    assert detect(write(tmp_path, "tool.bin", b"MZ" + b"\0" * 64)).key == "exe"


def test_unknown_file_is_none(tmp_path):
    assert detect(write(tmp_path, "notes.txt", b"just some words")) is None


def test_zip_with_unflagged_non_ascii_names_is_legacy(tmp_path):
    path = store_zip(tmp_path / "s.zip", "日本語.txt".encode("cp932"), b"x")
    assert zip_has_legacy_names(path) is True


def test_zip_with_flagged_utf8_names_is_not_legacy(tmp_path):
    path = tmp_path / "u.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("日本語.txt", "x")
    assert zip_has_legacy_names(path) is False


def test_ascii_zip_is_not_legacy(tmp_path):
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plain.txt", "x")
    assert zip_has_legacy_names(path) is False


def test_invalid_utf8_in_a_flagged_name_does_not_crash(tmp_path):
    path = store_zip(tmp_path / "b.zip", b"\xff\xfe\xfd.txt", b"x", flags=0x800)
    assert zip_has_legacy_names(path) is False


def test_unreadable_zip_is_not_legacy(tmp_path):
    assert zip_has_legacy_names(write(tmp_path, "bad.zip", b"PK\x03\x04broken")) is False
