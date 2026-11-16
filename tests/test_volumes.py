from pathlib import Path

import pytest

from ex.volumes import (
    archive_stem,
    first_volume,
    has_zip_segments,
    is_later_volume,
    is_numbered_split,
    looks_like_archive,
    missing_split_part,
)


def touch(directory, *names):
    for name in names:
        (directory / name).touch()


@pytest.mark.parametrize(
    "given,existing,expected",
    [
        ("d.part3.rar", ["d.part1.rar", "d.part2.rar", "d.part3.rar"], "d.part1.rar"),
        ("d.part03.rar", ["d.part01.rar", "d.part03.rar"], "d.part01.rar"),
        ("d.7z.002", ["d.7z.001", "d.7z.002"], "d.7z.001"),
        ("d.r05", ["d.rar", "d.r05"], "d.rar"),
        ("d.z02", ["d.zip", "d.z01", "d.z02"], "d.zip"),
        ("plain.zip", ["plain.zip"], "plain.zip"),
    ],
)
def test_any_volume_maps_to_the_first(tmp_path, given, existing, expected):
    touch(tmp_path, *existing)
    assert first_volume(tmp_path / given).name == expected


def test_uppercase_volumes_keep_the_spelling_on_disk(tmp_path):
    touch(tmp_path, "X.PART1.RAR", "X.PART2.RAR")
    assert first_volume(tmp_path / "X.PART2.RAR").name == "X.PART1.RAR"
    assert is_later_volume(tmp_path / "X.PART1.RAR") is False


def test_old_rar_set_resolves_to_the_stored_spelling(tmp_path):
    touch(tmp_path, "y.RAR", "y.R00")
    assert first_volume(tmp_path / "y.R00").name == "y.RAR"


def test_first_volume_in_a_missing_directory_is_harmless(tmp_path):
    ghost = tmp_path / "nope" / "d.part2.rar"
    assert first_volume(ghost) == ghost


def test_a_missing_first_volume_leaves_the_path_alone(tmp_path):
    touch(tmp_path, "d.part2.rar")
    assert first_volume(tmp_path / "d.part2.rar").name == "d.part2.rar"


def test_later_volume_is_recognised(tmp_path):
    touch(tmp_path, "d.part1.rar", "d.part2.rar")
    assert is_later_volume(tmp_path / "d.part2.rar") is True
    assert is_later_volume(tmp_path / "d.part1.rar") is False


@pytest.mark.parametrize(
    "name,stem",
    [
        ("x.tar.gz", "x"),
        ("x.tgz", "x"),
        ("x.tar.7z", "x"),
        ("data.part3.rar", "data"),
        ("big.7z.001", "big"),
        ("big.tar.gz.001", "big"),
        ("a.zip", "a"),
        ("photos.tar.zst", "photos"),
        ("noext", "noext"),
        ("report.docx", "report"),
        ("set.r05", "set"),
        ("a.z03", "a"),
        ("note.txt.gz", "note.txt"),
        ("v1.2.3.zip", "v1.2.3"),
        (".zip", ".zip"),
    ],
)
def test_archive_stem(name, stem):
    assert archive_stem(Path(name)) == stem


@pytest.mark.parametrize(
    "name,expected",
    [
        ("x.zip.001", True),
        ("x.tar.gz.001", True),
        ("movie.mp4.001", True),
        ("x.7z.001", False),
        ("notes.v2.10", False),
        ("x.zip", False),
    ],
)
def test_numbered_split_excludes_native_7z_volumes(name, expected):
    assert is_numbered_split(Path(name)) is expected


def test_gap_in_a_split_is_found(tmp_path):
    touch(tmp_path, "t.iso.001", "t.iso.003")
    assert missing_split_part(tmp_path / "t.iso.001") == 2


def test_complete_split_has_no_gap(tmp_path):
    touch(tmp_path, "t.iso.001", "t.iso.002", "other.iso.005")
    assert missing_split_part(tmp_path / "t.iso.001") is None


def test_zip_segments_need_a_z01_sibling(tmp_path):
    touch(tmp_path, "a.zip", "a.z01", "b.zip")
    assert has_zip_segments(tmp_path / "a.zip") is True
    assert has_zip_segments(tmp_path / "b.zip") is False


@pytest.mark.parametrize(
    "name,expected",
    [
        ("x.zip", True),
        ("X.RAR", True),
        ("x.7z.001", True),
        ("x.tar.zst", True),
        ("report.docx", False),
        ("app.exe", False),
        ("disk.iso", False),
        ("movie.mp4.001", False),
    ],
)
def test_directory_scans_only_pick_real_archives(name, expected):
    assert looks_like_archive(Path(name)) is expected
