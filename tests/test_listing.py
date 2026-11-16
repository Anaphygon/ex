import os
import subprocess
import tarfile
import zipfile

import pytest

from ex.extract import PasswordBook, inspect
from ex.listing import list_archive
from tests.builders import store_zip

PASSWORD = "secret"


def sh(*argv, cwd=None):
    subprocess.run(argv, check=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "payload" / "sub").mkdir(parents=True)
    (root / "payload" / "a b.txt").write_text("alpha\n")
    (root / "payload" / "sub" / "c.txt").write_text("gamma gamma\n")
    return root


@pytest.fixture
def box(tmp_path):
    path = tmp_path / "box"
    path.mkdir()
    return path


def listing_of(path, ask=None, preset=None):
    return list_archive(inspect(path), PasswordBook(ask or (lambda *_: None), preset))


def files_of(listing):
    return sorted(entry.path for entry in listing.entries if not entry.is_dir)


EXPECTED = ["payload/a b.txt", "payload/sub/c.txt"]

BUILDERS = {
    "x.zip": lambda s, o: sh("7zz", "a", "-tzip", o, "payload", cwd=s),
    "x.7z": lambda s, o: sh("7zz", "a", o, "payload", cwd=s),
    "x.rar": lambda s, o: sh("rar", "a", "-idq", o, "payload", cwd=s),
    "x.tar": lambda s, o: sh("tar", "cf", o, "payload", cwd=s),
    "x.tar.gz": lambda s, o: sh("tar", "czf", o, "payload", cwd=s),
    "x.tar.xz": lambda s, o: sh("tar", "cJf", o, "payload", cwd=s),
    "x.tar.zst": lambda s, o: subprocess.run(
        ["/bin/sh", "-c", f"tar cf - payload | zstd -q -o '{o}'"], cwd=s, check=True
    ),
}


@pytest.mark.parametrize("name", BUILDERS)
def test_lists_the_files_of_every_common_format(source, box, name):
    BUILDERS[name](source, box / name)
    listing = listing_of(box / name)
    assert listing.error is None
    assert files_of(listing) == EXPECTED


def test_entries_carry_sizes_and_times(source, box):
    BUILDERS["x.7z"](source, box / "x.7z")
    entry = next(e for e in listing_of(box / "x.7z").entries if e.path == "payload/sub/c.txt")
    assert entry.size == len("gamma gamma\n")
    assert entry.modified is not None and entry.modified > 1_600_000_000
    assert entry.encrypted is False


def test_directories_are_marked(source, box):
    BUILDERS["x.zip"](source, box / "x.zip")
    dirs = {e.path for e in listing_of(box / "x.zip").entries if e.is_dir}
    assert "payload/sub" in dirs


def test_mac_junk_is_hidden(box):
    with zipfile.ZipFile(box / "m.zip", "w") as archive:
        archive.writestr("p/a.txt", "1")
        archive.writestr("__MACOSX/p/._a.txt", "x")
        archive.writestr("p/.DS_Store", "x")
    assert files_of(listing_of(box / "m.zip")) == ["p/a.txt"]


def test_leading_dot_slash_is_normalised(tmp_path, box):
    (tmp_path / "f.txt").write_text("x")
    sh("tar", "cf", box / "t.tar", "./f.txt", cwd=tmp_path)
    assert files_of(listing_of(box / "t.tar")) == ["f.txt"]


def test_plain_compressed_file_lists_its_single_member(box):
    (box / "note.txt").write_text("hello")
    sh("gzip", "-k", box / "note.txt")
    assert files_of(listing_of(box / "note.txt.gz")) == ["note.txt"]


def test_legacy_zip_names_are_decoded(box):
    store_zip(box / "s.zip", "日本語のファイル.txt".encode("cp932"), b"x")
    assert files_of(listing_of(box / "s.zip")) == ["日本語のファイル.txt"]


def test_encrypted_entries_are_flagged_without_asking(source, box):
    sh("7zz", "a", f"-p{PASSWORD}", box / "e.7z", "payload", cwd=source)

    def never(*_):
        raise AssertionError("should not prompt")

    listing = listing_of(box / "e.7z", never)
    assert files_of(listing) == EXPECTED
    assert all(e.encrypted for e in listing.entries if not e.is_dir)


@pytest.mark.parametrize(
    "name,build",
    [
        ("h.7z", lambda o, s: sh("7zz", "a", f"-p{PASSWORD}", "-mhe=on", o, "payload", cwd=s)),
        ("h.rar", lambda o, s: sh("rar", "a", "-idq", f"-hp{PASSWORD}", o, "payload", cwd=s)),
    ],
)
def test_encrypted_headers_ask_for_the_password(source, box, name, build):
    build(box / name, source)
    answers = iter(["wrong", PASSWORD])
    retries = []

    def ask(archive, retry):
        retries.append(retry)
        return next(answers)

    listing = listing_of(box / name, ask)
    assert listing.error is None, listing.error
    assert files_of(listing) == EXPECTED
    assert retries == [False, True]


def test_cancelled_password_is_an_error(source, box):
    sh("7zz", "a", f"-p{PASSWORD}", "-mhe=on", box / "h.7z", "payload", cwd=source)
    listing = listing_of(box / "h.7z")
    assert listing.error and not listing.entries


def test_byte_split_lists_the_real_contents(source, box):
    BUILDERS["x.zip"](source, box / "w.zip")
    data = (box / "w.zip").read_bytes()
    (box / "w.zip").unlink()
    (box / "w.zip.001").write_bytes(data[:200])
    (box / "w.zip.002").write_bytes(data[200:])
    assert files_of(listing_of(box / "w.zip.001")) == EXPECTED


@pytest.mark.parametrize(
    "name,command",
    [
        ("x.tar.lz4", "tar cf - payload | lz4 -q - '{out}'"),
        ("x.tar.br", "tar cf - payload | brotli -c > '{out}'"),
        ("x.tar.lzma", "tar cf - payload | xz --format=lzma -c > '{out}'"),
    ],
)
def test_tar_inside_any_compressor_is_listed(source, box, name, command):
    subprocess.run(["/bin/sh", "-c", command.format(out=box / name)], cwd=source, check=True)
    assert files_of(listing_of(box / name)) == EXPECTED


def test_non_utf8_tar_names_are_listed(box):
    with tarfile.open(box / "latin.tar", "w", encoding="latin-1") as archive:
        info = tarfile.TarInfo("caf\xe9.txt")
        info.size = 1
        import io
        archive.addfile(info, io.BytesIO(b"x"))
    listing = listing_of(box / "latin.tar")
    assert listing.error is None and files_of(listing) == ["café.txt"]


@pytest.mark.parametrize("entries", [{}, {"__MACOSX/._x": "x", ".DS_Store": "x"}])
def test_empty_archive_lists_as_empty_not_damaged(box, entries):
    with zipfile.ZipFile(box / "e.zip", "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    listing = listing_of(box / "e.zip")
    assert listing.error is None and listing.entries == ()


def test_non_archive_is_an_error(box):
    (box / "notes.txt").write_text("hello there")
    assert listing_of(box / "notes.txt").error


def test_damaged_archive_is_an_error(source, box):
    (source / "payload" / "big.bin").write_bytes(os.urandom(200_000))
    BUILDERS["x.7z"](source, box / "x.7z")
    (box / "x.7z").write_bytes((box / "x.7z").read_bytes()[:3000])
    assert listing_of(box / "x.7z").error


def test_missing_file_is_an_error(box):
    assert listing_of(box / "ghost.zip").error


def test_listing_reports_the_format_label(source, box):
    BUILDERS["x.rar"](source, box / "x.rar")
    assert listing_of(box / "x.rar").label == "rar5"
