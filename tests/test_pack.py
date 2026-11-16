import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from ex.extract import Options, PasswordBook, extract, inspect
from ex.pack import PACK_FORMATS, PackOptions, available_formats, pack

PASSWORD = "secret"


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "src"
    (root / "folder" / "sub").mkdir(parents=True)
    (root / "folder" / "a.txt").write_text("alpha\n")
    (root / "folder" / "sub" / "b.txt").write_text("beta\n")
    (root / "folder" / ".DS_Store").write_text("junk")
    (root / "loose.txt").write_text("loose\n")
    return root


@pytest.fixture
def out(tmp_path):
    path = tmp_path / "out"
    path.mkdir()
    return path


def roundtrip(archive, tmp_path, password=None):
    dest = tmp_path / "back"
    outcome = extract(inspect(archive), Options(output_dir=dest), PasswordBook(lambda *_: password))
    assert outcome.ok, outcome.error
    return outcome.output


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize("fmt", ["zip", "7z", "tar", "tar.gz", "tar.xz", "tar.zst", "rar"])
def test_every_format_round_trips_without_mac_junk(sources, out, tmp_path, fmt):
    result = pack([sources / "folder", sources / "loose.txt"], out, "bundle", PackOptions(fmt))
    assert result.ok, result.error
    assert [p.name for p in result.outputs] == [f"bundle.{fmt}"]
    restored = roundtrip(result.outputs[0], tmp_path)
    assert tree(restored) == ["folder/a.txt", "folder/sub/b.txt", "loose.txt"]


def test_a_single_folder_round_trips_as_that_folder(sources, out, tmp_path):
    result = pack([sources / "folder"], out, "folder", PackOptions("zip"))
    restored = roundtrip(result.outputs[0], tmp_path)
    assert restored.name == "folder" and (restored / "sub" / "b.txt").read_text() == "beta\n"


@pytest.mark.parametrize("fmt", ["zip", "7z", "rar"])
def test_password_protects_the_archive(sources, out, tmp_path, fmt):
    result = pack([sources / "folder"], out, "locked", PackOptions(fmt, password=PASSWORD))
    assert result.ok, result.error
    refused = extract(inspect(result.outputs[0]), Options(output_dir=tmp_path / "no"), PasswordBook(lambda *_: None))
    assert not refused.ok
    assert (roundtrip(result.outputs[0], tmp_path, PASSWORD) / "a.txt").exists()


@pytest.mark.parametrize("fmt", ["7z", "rar"])
def test_encrypted_names_hide_the_listing(sources, out, fmt):
    result = pack([sources / "folder"], out, "hidden", PackOptions(fmt, password=PASSWORD, encrypt_names=True))
    assert result.ok, result.error
    listed = subprocess.run(["7zz", "l", "-p", str(result.outputs[0])], capture_output=True, text=True)
    assert "a.txt" not in listed.stdout


def big_sources(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    (root / "blob.bin").write_bytes(os.urandom(300_000))
    return root


@pytest.mark.parametrize("fmt,first", [("7z", "parts.7z.001"), ("zip", "parts.zip.001"), ("rar", "parts.part1.rar")])
def test_volumes_split_and_reassemble(tmp_path, out, fmt, first):
    result = pack([big_sources(tmp_path)], out, "parts", PackOptions(fmt, level=0, volume_bytes=100_000))
    assert result.ok, result.error
    assert len(result.outputs) >= 3 and result.outputs[0].name == first
    restored = roundtrip(result.outputs[-1], tmp_path)
    assert (restored / "blob.bin").stat().st_size == 300_000


def test_existing_archive_is_never_overwritten(sources, out):
    (out / "bundle.zip").write_text("precious")
    result = pack([sources / "loose.txt"], out, "bundle", PackOptions("zip"))
    assert result.outputs[0].name == "bundle (2).zip"
    assert (out / "bundle.zip").read_text() == "precious"


def test_volume_sets_are_renamed_together(tmp_path, out):
    (out / "parts.7z.002").write_text("taken")
    result = pack([big_sources(tmp_path)], out, "parts", PackOptions("7z", level=0, volume_bytes=100_000))
    assert all(p.name.startswith("parts (2).7z.") for p in result.outputs)
    assert (out / "parts.7z.002").read_text() == "taken"


@pytest.mark.parametrize("level", [0, 1, 5, 9])
def test_every_level_is_accepted(sources, out, level):
    for fmt in ("zip", "7z", "tar.gz", "tar.xz", "tar.zst"):
        assert pack([sources / "loose.txt"], out, f"l{level}", PackOptions(fmt, level=level)).ok


def test_higher_level_compresses_better(tmp_path, out):
    root = tmp_path / "text"
    root.mkdir()
    (root / "t.txt").write_text("the quick brown fox " * 50_000)
    stored = pack([root], out, "stored", PackOptions("zip", level=0)).outputs[0]
    squeezed = pack([root], out, "squeezed", PackOptions("zip", level=9)).outputs[0]
    assert squeezed.stat().st_size < stored.stat().st_size / 10


def test_tar_keeps_symlinks_as_links(tmp_path, out):
    root = tmp_path / "links"
    root.mkdir()
    (root / "target.txt").write_text("x")
    (root / "link").symlink_to("target.txt")
    result = pack([root], out, "l", PackOptions("tar.gz"))
    with tarfile.open(result.outputs[0]) as archive:
        assert archive.getmember("links/link").issym()


def test_tar_skips_sockets(out):
    import socket
    import tempfile

    # Unix socket paths are limited to ~104 bytes, too short for pytest's tmp_path.
    root = Path(tempfile.mkdtemp(dir="/tmp")) / "s"
    root.mkdir()
    (root / "keep.txt").write_text("x")
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(root / "db.sock"))
    try:
        result = pack([root], out, "s", PackOptions("tar.gz"))
    finally:
        server.close()
    assert result.ok, result.error
    with tarfile.open(result.outputs[0]) as archive:
        assert archive.getnames() == ["s", "s/keep.txt"]


def test_tar_reports_progress(tmp_path, out):
    seen = []
    pack([big_sources(tmp_path)], out, "p", PackOptions("tar.gz"), on_tick=seen.append)
    assert seen and max(p for p in seen if p is not None) == 100


@pytest.mark.parametrize(
    "options,message",
    [
        (PackOptions("tar.gz", password=PASSWORD), "password"),
        (PackOptions("tar.xz", volume_bytes=1000), "split"),
        (PackOptions("zip", password=PASSWORD, encrypt_names=True), "names"),
        (PackOptions("nope"), "format"),
    ],
)
def test_unsupported_combinations_are_refused(sources, out, options, message):
    result = pack([sources / "loose.txt"], out, "x", options)
    assert not result.ok and message in result.error.lower()


@pytest.mark.parametrize("name", ["", "a/b", ".", ".."])
def test_bad_names_are_refused(sources, out, name):
    assert not pack([sources / "loose.txt"], out, name, PackOptions("zip")).ok


def test_missing_source_is_refused(sources, out):
    result = pack([sources / "ghost"], out, "x", PackOptions("zip"))
    assert not result.ok and "ghost" in result.error


def test_no_sources_is_refused(out):
    assert not pack([], out, "x", PackOptions("zip")).ok


def test_failure_leaves_nothing_behind(sources, out, monkeypatch):
    from ex import pack as pack_module

    monkeypatch.setattr(pack_module, "_run_tool", lambda *a, **k: pack_module.RunResult(2, "ERROR: boom"))
    result = pack([sources / "loose.txt"], out, "x", PackOptions("7z"))
    assert not result.ok and list(out.iterdir()) == []


def test_interrupt_leaves_nothing_behind(tmp_path, out):
    def interrupt(_percent):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        pack([big_sources(tmp_path)], out, "x", PackOptions("tar.gz"), on_tick=interrupt)
    assert list(out.iterdir()) == []


def test_sources_from_different_folders(tmp_path, out):
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    (tmp_path / "one" / "a.txt").write_text("1")
    (tmp_path / "two" / "b.txt").write_text("2")
    result = pack([tmp_path / "one" / "a.txt", tmp_path / "two" / "b.txt"], out, "mix", PackOptions("7z"))
    listed = subprocess.run(["7zz", "l", "-ba", "-slt", str(result.outputs[0])], capture_output=True, text=True).stdout
    assert "Path = a.txt" in listed and "Path = b.txt" in listed


def test_available_formats_include_the_basics():
    assert {"zip", "7z", "tar.gz"} <= set(available_formats())
    assert set(available_formats()) <= set(PACK_FORMATS)
