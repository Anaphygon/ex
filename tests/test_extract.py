import os
import subprocess
import tarfile
import io
import unicodedata
import zipfile
from pathlib import Path

import pytest

from ex.extract import DAMAGED, Options, PasswordBook, extract, inspect
from tests.builders import store_rar4, store_zip

PASSWORD = "secret"


def sh(*argv, cwd=None):
    subprocess.run(argv, check=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pipe(command, cwd):
    subprocess.run(["/bin/sh", "-c", command], check=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "payload" / "sub").mkdir(parents=True)
    (root / "payload" / "a.txt").write_text("alpha\n")
    (root / "payload" / "sub" / "b.txt").write_text("beta\n")
    return root


@pytest.fixture
def box(tmp_path):
    path = tmp_path / "box"
    path.mkdir()
    return path


def run_extract(path, ask=None, preset=None, on_tick=None, **options):
    options = {**options, "only": tuple(options.get("only", ()))}
    book = PasswordBook(ask or (lambda *_: None), preset)
    return extract(inspect(path), Options(**options), book, on_tick)


def assert_payload(folder):
    assert (folder / "a.txt").read_text() == "alpha\n"
    assert (folder / "sub" / "b.txt").read_text() == "beta\n"


def no_leftovers(folder):
    return not [p.name for p in folder.iterdir() if p.name.startswith(".ex-")]


ROUND_TRIPS = {
    "x.zip": lambda s, o: sh("7zz", "a", "-tzip", o, "payload", cwd=s),
    "x.7z": lambda s, o: sh("7zz", "a", o, "payload", cwd=s),
    "x.rar": lambda s, o: sh("rar", "a", "-idq", o, "payload", cwd=s),
    "x.tar": lambda s, o: sh("tar", "cf", o, "payload", cwd=s),
    "x.tar.gz": lambda s, o: sh("tar", "czf", o, "payload", cwd=s),
    "x.tgz": lambda s, o: sh("tar", "czf", o, "payload", cwd=s),
    "x.tar.bz2": lambda s, o: sh("tar", "cjf", o, "payload", cwd=s),
    "x.tar.xz": lambda s, o: sh("tar", "cJf", o, "payload", cwd=s),
    "x.tar.zst": lambda s, o: pipe(f"tar cf - payload | zstd -q -o '{o}'", s),
    "x.tar.lz4": lambda s, o: pipe(f"tar cf - payload | lz4 -q - '{o}'", s),
    "x.tar.br": lambda s, o: pipe(f"tar cf - payload | brotli -c > '{o}'", s),
    "x.cpio": lambda s, o: pipe(f"find payload | cpio -o > '{o}'", s),
    "x.xar": lambda s, o: sh("xar", "-cf", o, "payload", cwd=s),
}


@pytest.mark.parametrize("name", ROUND_TRIPS)
def test_every_format_extracts_to_the_original_tree(source, box, name):
    archive = box / name
    ROUND_TRIPS[name](source, archive)
    outcome = run_extract(archive)
    assert outcome.ok, outcome.error
    assert outcome.output == box / "payload"
    assert_payload(outcome.output)
    assert no_leftovers(box)


def test_tar_wrapped_in_7z_is_unwrapped(source, box):
    tar_path = box / "inner.tar"
    sh("tar", "cf", tar_path, "payload", cwd=source)
    sh("7zz", "a", box / "x.tar.7z", tar_path)
    tar_path.unlink()
    outcome = run_extract(box / "x.tar.7z")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


@pytest.mark.parametrize(
    "name,command",
    [
        ("note.txt.gz", "gzip -c note.txt"),
        ("note.txt.bz2", "bzip2 -c note.txt"),
        ("note.txt.xz", "xz -c note.txt"),
        ("note.txt.zst", "zstd -q -c note.txt"),
        ("note.txt.lz4", "lz4 -q -c note.txt"),
        ("note.txt.br", "brotli -c note.txt"),
    ],
)
def test_plain_compressed_files_become_one_file(source, box, name, command):
    (source / "note.txt").write_text("single\n")
    pipe(f"{command} > '{box / name}'", source)
    outcome = run_extract(box / name)
    assert outcome.ok, outcome.error
    assert outcome.output == box / "note.txt"
    assert outcome.output.read_text() == "single\n"


def test_old_rar4_archive(box):
    outcome = run_extract(store_rar4(box / "old.rar", "hello.txt", b"from rar4"))
    assert outcome.ok, outcome.error
    assert outcome.output.read_bytes() == b"from rar4"
    assert outcome.label == "rar4"


def test_iso_image(source, box):
    sh("hdiutil", "makehybrid", "-quiet", "-iso", "-joliet", "-o", box / "x.iso", source / "payload")
    outcome = run_extract(box / "x.iso")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


@pytest.mark.parametrize("filesystem,fmt", [("HFS+", "UDZO"), ("APFS", "UDZO"), ("HFS+", "UDBZ")])
def test_disk_image_comes_out_without_filesystem_debris(source, box, filesystem, fmt):
    image = box / "x.dmg"
    sh("hdiutil", "create", "-quiet", "-fs", filesystem, "-volname", "Vol", "-srcfolder", source / "payload", "-format", fmt, image)
    outcome = run_extract(image)
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)
    names = [p.name for p in outcome.output.rglob("*")]
    assert not [n for n in names if ":" in n or "HFS+ Private" in n or n in {".fseventsd", ".Trashes"}]


def zip_with(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_many_top_level_entries_get_a_folder_named_after_the_archive(box):
    outcome = run_extract(zip_with(box / "bundle.zip", {"a.txt": "1", "b.txt": "2"}))
    assert outcome.output == box / "bundle"
    assert outcome.files == 2


def test_single_file_lands_next_to_the_archive(box):
    outcome = run_extract(zip_with(box / "wrapper.zip", {"report.pdf": "pdf"}))
    assert outcome.output == box / "report.pdf"


def test_macos_junk_does_not_defeat_the_single_folder_rule(box):
    outcome = run_extract(
        zip_with(box / "m.zip", {"payload/a.txt": "1", "__MACOSX/payload/._a.txt": "x", ".DS_Store": "x"})
    )
    assert outcome.output == box / "payload"
    assert sorted(p.name for p in box.iterdir()) == ["m.zip", "payload"]


def test_existing_results_are_never_overwritten(box):
    archive = zip_with(box / "m.zip", {"payload/a.txt": "new"})
    (box / "payload").mkdir()
    (box / "payload" / "mine.txt").write_text("precious")
    outcome = run_extract(archive)
    assert outcome.output == box / "payload (2)"
    assert (box / "payload" / "mine.txt").read_text() == "precious"


def test_output_directory_is_created_and_used(box, tmp_path):
    target = tmp_path / "new" / "place"
    outcome = run_extract(zip_with(box / "m.zip", {"a/b.txt": "1"}), output_dir=target)
    assert outcome.output == target / "a"


def test_archive_is_left_in_place(box):
    archive = zip_with(box / "m.zip", {"a.txt": "1"})
    before = archive.read_bytes()
    run_extract(archive)
    assert archive.read_bytes() == before


@pytest.mark.parametrize("name", ["with space.zip", "-dash.zip", "quo'te\"s.zip", "ünï çödé 日本.zip"])
def test_awkward_archive_names(box, name):
    outcome = run_extract(zip_with(box / name, {"payload/a.txt": "1"}))
    assert outcome.ok, outcome.error
    assert (outcome.output / "a.txt").read_text() == "1"


def test_awkward_entry_names(box):
    names = {"payload/-dash.txt": "1", "payload/sp ace.txt": "2", "payload/日本語.txt": "3"}
    outcome = run_extract(zip_with(box / "m.zip", names))
    assert outcome.ok, outcome.error
    assert outcome.files == 3
    assert (outcome.output / "日本語.txt").read_text() == "3"


def test_legacy_encoded_zip_names_survive(box):
    outcome = run_extract(store_zip(box / "s.zip", "日本語のファイル.txt".encode("cp932"), b"x"))
    assert outcome.ok, outcome.error
    assert outcome.output.name == "日本語のファイル.txt"


def test_utf8_zip_without_the_flag_survives(box):
    outcome = run_extract(store_zip(box / "mac.zip", "café résumé.txt".encode(), b"x"))
    assert outcome.ok, outcome.error
    # macOS tools write names decomposed (NFD); the visible name is the same.
    assert unicodedata.normalize("NFC", outcome.output.name) == "café résumé.txt"


def tar_with(path, build):
    with tarfile.open(path, "w") as archive:
        build(archive)
    return path


def add_file(archive, name, content=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def add_link(archive, name, target):
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    archive.addfile(info)


def test_escaping_symlinks_are_dropped_with_a_note(box):
    def build(archive):
        add_file(archive, "payload/ok.txt")
        add_link(archive, "payload/bad", "/etc/passwd")
        add_link(archive, "payload/good", "ok.txt")

    outcome = run_extract(tar_with(box / "t.tar", build))
    assert outcome.ok, outcome.error
    assert not os.path.lexists(outcome.output / "bad")
    assert (outcome.output / "good").is_symlink()
    assert any("symlink" in note for note in outcome.notes)


@pytest.mark.parametrize("name", ["../evil.txt", "../../evil.txt"])
def test_traversal_entries_stay_inside(box, tmp_path, name):
    def build(archive):
        add_file(archive, name, b"evil")
        add_file(archive, "ok.txt")

    run_extract(tar_with(box / "t.tar", build))
    written = [p for p in tmp_path.rglob("evil.txt") if box not in p.parents]
    assert written == []
    assert no_leftovers(box)


def test_writing_through_a_symlink_is_refused(box, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    def build(archive):
        add_link(archive, "link", str(outside))
        add_file(archive, "link/evil.txt", b"evil")

    run_extract(tar_with(box / "t.tar", build))
    assert list(outside.iterdir()) == []
    assert no_leftovers(box)


ENCRYPTED = {
    "z.zip": lambda p, o: sh("zip", "-q", "-P", p, "-r", o, "payload"),
    "aes.zip": lambda p, o: sh("7zz", "a", "-tzip", "-mem=AES256", f"-p{p}", o, "payload"),
    "x.7z": lambda p, o: sh("7zz", "a", f"-p{p}", o, "payload"),
    "hdr.7z": lambda p, o: sh("7zz", "a", f"-p{p}", "-mhe=on", o, "payload"),
    "x.rar": lambda p, o: sh("rar", "a", "-idq", f"-p{p}", o, "payload"),
    "hdr.rar": lambda p, o: sh("rar", "a", "-idq", f"-hp{p}", o, "payload"),
}


@pytest.fixture
def encrypted(source, box, monkeypatch):
    def make(name):
        monkeypatch.chdir(source)
        ENCRYPTED[name](PASSWORD, box / name)
        return box / name

    return make


@pytest.mark.parametrize("name", ENCRYPTED)
def test_encrypted_archive_asks_and_extracts(encrypted, name):
    asked = []

    def ask(archive, retry):
        asked.append(retry)
        return PASSWORD

    outcome = run_extract(encrypted(name), ask)
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)
    assert asked == [False]


@pytest.mark.parametrize("name", ENCRYPTED)
def test_wrong_password_can_be_retried(encrypted, name):
    answers = iter(["nope", PASSWORD])
    retries = []

    def ask(archive, retry):
        retries.append(retry)
        return next(answers)

    outcome = run_extract(encrypted(name), ask)
    assert outcome.ok, outcome.error
    assert retries == [False, True]


def test_preset_password_is_used_without_asking(encrypted):
    def never(*_):
        raise AssertionError("should not prompt")

    outcome = run_extract(encrypted("x.7z"), never, preset=PASSWORD)
    assert outcome.ok, outcome.error


def test_cancelling_the_prompt_fails_cleanly(encrypted, box):
    outcome = run_extract(encrypted("x.7z"))
    assert not outcome.ok
    assert no_leftovers(box)


def test_always_wrong_password_gives_up(encrypted, box):
    calls = []

    def ask(archive, retry):
        calls.append(retry)
        return "nope"

    outcome = run_extract(encrypted("x.7z"), ask)
    assert not outcome.ok
    assert len(calls) == 3
    assert "assword" in outcome.error


def test_a_batch_only_asks_once(encrypted, box):
    first, second = encrypted("x.7z"), encrypted("hdr.7z")
    calls = []

    def ask(archive, retry):
        calls.append(archive.name)
        return PASSWORD

    book = PasswordBook(ask)
    results = [extract(inspect(path), Options(output_dir=box / path.stem), book) for path in (first, second)]
    assert all(result.ok for result in results)
    assert calls == ["x.7z"]


def blob(source, size=400_000):
    (source / "payload" / "blob.bin").write_bytes(os.urandom(size))


def test_rar_volumes_from_any_part(source, box):
    blob(source)
    sh("rar", "a", "-idq", "-v100k", box / "big.rar", "payload", cwd=source)
    job = inspect(box / "big.part2.rar")
    assert job.archive.name == "big.part1.rar"
    outcome = extract(job, Options(), PasswordBook(lambda *_: None))
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


def test_7z_volumes_from_any_part(source, box):
    blob(source)
    sh("7zz", "a", "-v100k", box / "big.7z", "payload", cwd=source)
    outcome = run_extract(box / "big.7z.002")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


def test_split_zip_segments(source, box):
    blob(source)
    sh("zip", "-q", "-r", "-s", "100k", box / "big.zip", "payload", cwd=source)
    outcome = run_extract(box / "big.z01")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


def byte_split(path, chunk=150_000):
    data = path.read_bytes()
    path.unlink()
    pieces = [data[i : i + chunk] for i in range(0, len(data), chunk)]
    for index, piece in enumerate(pieces, start=1):
        Path(f"{path}.{index:03d}").write_bytes(piece)
    return len(pieces)


def test_byte_split_zip_is_joined_then_extracted(source, box):
    blob(source)
    sh("7zz", "a", "-tzip", box / "w.zip", "payload", cwd=source)
    byte_split(box / "w.zip")
    outcome = run_extract(box / "w.zip.002")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


def test_byte_split_tar_gz_is_joined_then_extracted(source, box):
    blob(source)
    sh("tar", "czf", box / "g.tar.gz", "payload", cwd=source)
    byte_split(box / "g.tar.gz")
    outcome = run_extract(box / "g.tar.gz.001")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


def test_byte_split_of_a_non_archive_rejoins_the_file(box):
    data = os.urandom(400_000)
    (box / "movie.mp4").write_bytes(data)
    byte_split(box / "movie.mp4")
    outcome = run_extract(box / "movie.mp4.001")
    assert outcome.ok, outcome.error
    assert outcome.output.read_bytes() == data


def test_missing_part_is_a_failure_not_a_half_result(source, box):
    blob(source)
    sh("7zz", "a", "-tzip", box / "w.zip", "payload", cwd=source)
    byte_split(box / "w.zip")
    (box / "w.zip.002").unlink()
    outcome = run_extract(box / "w.zip.001")
    assert not outcome.ok
    assert no_leftovers(box)
    assert not (box / "payload").exists() and not (box / "w.zip").exists()


def test_corrupt_archive_fails_cleanly(source, box):
    blob(source)
    sh("7zz", "a", box / "x.7z", "payload", cwd=source)
    data = bytearray((box / "x.7z").read_bytes())
    data[200:220] = b"\xff" * 20
    (box / "x.7z").write_bytes(data)
    outcome = run_extract(box / "x.7z")
    assert not outcome.ok and outcome.error
    assert no_leftovers(box)


@pytest.mark.parametrize(
    "name,build",
    [
        ("t.7z", lambda s, o: sh("7zz", "a", o, "payload", cwd=s)),
        ("t.rar", lambda s, o: sh("rar", "a", "-idq", o, "payload", cwd=s)),
        ("t.tar.gz", lambda s, o: sh("tar", "czf", o, "payload", cwd=s)),
    ],
)
def test_truncated_archive_is_called_damaged(source, box, name, build):
    blob(source)
    build(source, box / name)
    (box / name).write_bytes((box / name).read_bytes()[:5000])
    outcome = run_extract(box / name)
    assert outcome.error == DAMAGED


def test_file_only_named_like_an_archive_is_called_damaged(box):
    (box / "fake.zip").write_bytes(os.urandom(2000))
    assert run_extract(box / "fake.zip").error == DAMAGED


def test_a_lenient_fallback_cannot_turn_damage_into_success(box):
    archive = zip_with(box / "cut.zip", {"p/a.txt": "1" * 500, "p/b.txt": "2" * 500, "p/c.txt": "3" * 500})
    with zipfile.ZipFile(archive) as opened:
        offset = opened.infolist()[2].header_offset
    archive.write_bytes(archive.read_bytes()[:offset])
    outcome = run_extract(archive)
    assert outcome.error == DAMAGED
    assert no_leftovers(box) and not (box / "p").exists()


def test_archive_name_cannot_fake_a_password_prompt(box):
    archive = zip_with(box / "passphrase-backup.zip", {"p/a.txt": "1" * 500, "p/b.txt": "2" * 500})
    archive.write_bytes(archive.read_bytes()[:300])

    def never(*_):
        raise AssertionError("should not prompt")

    assert run_extract(archive, never).error == DAMAGED


def test_read_only_top_folder_extracts(box):
    def build(archive):
        folder = tarfile.TarInfo("pkg")
        folder.type = tarfile.DIRTYPE
        folder.mode = 0o555
        archive.addfile(folder)
        add_file(archive, "pkg/a.txt")

    outcome = run_extract(tar_with(box / "t.tar", build))
    assert outcome.ok, outcome.error
    assert outcome.output == box / "pkg" and (outcome.output / "a.txt").exists()


def test_tar_with_mac_bookkeeping_is_still_unwrapped(source, box):
    sh("tar", "cf", box / "w.tar", "payload", cwd=source)
    with zipfile.ZipFile(box / "w.zip", "w") as archive:
        archive.write(box / "w.tar", "w.tar")
        archive.writestr("__MACOSX/._w.tar", "x")
    (box / "w.tar").unlink()
    outcome = run_extract(box / "w.zip")
    assert outcome.ok, outcome.error
    assert_payload(outcome.output)


def test_split_zip_with_legacy_names_survives(box):
    byte_split(store_zip(box / "j.zip", "日本語のファイル.txt".encode("cp932"), b"x" * 200), chunk=120)
    outcome = run_extract(box / "j.zip.001")
    assert outcome.ok, outcome.error
    assert outcome.output.name == "日本語のファイル.txt"


def test_gap_in_a_split_is_refused_up_front(box):
    (box / "t.iso.001").write_bytes(b"a" * 100)
    (box / "t.iso.003").write_bytes(b"c" * 100)
    outcome = run_extract(box / "t.iso.001")
    assert not outcome.ok and "002" in outcome.error
    assert not (box / "t.iso").exists() and no_leftovers(box)


def test_non_archive_is_a_clear_error(box):
    (box / "notes.txt").write_text("hello there, plain text")
    outcome = run_extract(box / "notes.txt")
    assert not outcome.ok
    assert "archive" in outcome.error.lower()
    assert no_leftovers(box)


def test_missing_file_is_a_clear_error(box):
    outcome = run_extract(box / "ghost.zip")
    assert not outcome.ok and outcome.error


def test_directory_is_a_clear_error(box):
    outcome = run_extract(box)
    assert not outcome.ok and outcome.error


def test_empty_archive_is_reported(box):
    outcome = run_extract(zip_with(box / "e.zip", {}))
    assert not outcome.ok
    assert no_leftovers(box)


def test_unwritable_destination_is_an_error_not_a_crash(box, tmp_path):
    archive = zip_with(box / "m.zip", {"a.txt": "1"})
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        outcome = run_extract(archive, output_dir=locked)
    finally:
        locked.chmod(0o700)
    assert not outcome.ok and outcome.error


def test_selection_extracts_only_the_chosen_items_flat(box, tmp_path):
    archive = zip_with(box / "m.zip", {"p/a.txt": "1", "p/b.txt": "2", "p/d/c.txt": "3"})
    outcome = run_extract(archive, output_dir=tmp_path / "pick", only=("p/a.txt", "p/d"))
    assert outcome.ok, outcome.error
    assert sorted(o.name for o in outcome.outputs) == ["a.txt", "d"]
    assert sorted(p.name for p in (tmp_path / "pick").iterdir()) == ["a.txt", "d"]
    assert (tmp_path / "pick" / "d" / "c.txt").read_text() == "3"


@pytest.mark.parametrize(
    "name,build",
    [
        ("x.7z", lambda s, o: sh("7zz", "a", o, "payload", cwd=s)),
        ("x.rar", lambda s, o: sh("rar", "a", "-idq", o, "payload", cwd=s)),
        ("x.tar.gz", lambda s, o: sh("tar", "czf", o, "payload", cwd=s)),
        ("x.tar.zst", lambda s, o: pipe(f"tar cf - payload | zstd -q -o '{o}'", s)),
    ],
)
def test_selection_works_for_every_backend(source, box, tmp_path, name, build):
    build(source, box / name)
    outcome = run_extract(box / name, output_dir=tmp_path / "pick", only=("payload/sub/b.txt",))
    assert outcome.ok, outcome.error
    assert outcome.output == tmp_path / "pick" / "b.txt"
    assert outcome.output.read_text() == "beta\n"


def test_selection_with_wildcard_characters_is_literal(box, tmp_path):
    archive = zip_with(box / "m.zip", {"p/st*ar.txt": "1", "p/stXar.txt": "2"})
    outcome = run_extract(archive, output_dir=tmp_path / "pick", only=("p/st*ar.txt",))
    assert [o.name for o in outcome.outputs] == ["st*ar.txt"]


def test_selection_never_overwrites(box, tmp_path):
    archive = zip_with(box / "m.zip", {"p/a.txt": "new"})
    (tmp_path / "pick").mkdir()
    (tmp_path / "pick" / "a.txt").write_text("mine")
    outcome = run_extract(archive, output_dir=tmp_path / "pick", only=("p/a.txt",))
    assert outcome.output.name == "a (2).txt"
    assert (tmp_path / "pick" / "a.txt").read_text() == "mine"


def test_selection_of_a_missing_item_fails_cleanly(box, tmp_path):
    archive = zip_with(box / "m.zip", {"p/a.txt": "1"})
    outcome = run_extract(archive, output_dir=tmp_path / "pick", only=("p/nope.txt",))
    assert not outcome.ok and "nope.txt" in outcome.error
    assert list((tmp_path / "pick").iterdir()) == []


@pytest.mark.parametrize("bad", ["../evil", "/etc/passwd", "p/../../x", ""])
def test_selection_cannot_escape(box, tmp_path, bad):
    archive = zip_with(box / "m.zip", {"p/a.txt": "1"})
    outcome = run_extract(archive, output_dir=tmp_path / "pick", only=(bad,))
    assert not outcome.ok


def test_selected_folder_drops_links_that_leave_it(box, tmp_path):
    def build(archive):
        add_file(archive, "p/secret.txt")
        add_file(archive, "p/d/ok.txt")
        add_link(archive, "p/d/up", "../secret.txt")
        add_link(archive, "p/d/inside", "ok.txt")

    outcome = run_extract(tar_with(box / "t.tar", build), output_dir=tmp_path / "pick", only=("p/d",))
    assert outcome.ok, outcome.error
    assert not os.path.lexists(outcome.output / "up")
    assert (outcome.output / "inside").is_symlink()


def test_selected_symlink_is_dropped(box, tmp_path):
    def build(archive):
        add_file(archive, "p/a.txt")
        add_link(archive, "p/l", "a.txt")

    outcome = run_extract(tar_with(box / "t.tar", build), output_dir=tmp_path / "pick", only=("p/l", "p/a.txt"))
    assert [o.name for o in outcome.outputs] == ["a.txt"]
    assert outcome.notes


def test_selection_out_of_a_read_only_folder(box, tmp_path):
    def build(archive):
        folder = tarfile.TarInfo("p")
        folder.type = tarfile.DIRTYPE
        folder.mode = 0o555
        archive.addfile(folder)
        add_file(archive, "p/a.txt")

    outcome = run_extract(tar_with(box / "t.tar", build), output_dir=tmp_path / "pick", only=("p/a.txt",))
    assert outcome.ok, outcome.error


def test_selecting_a_tar_inside_an_archive_keeps_it_a_tar(source, box, tmp_path):
    sh("tar", "cf", box / "data.tar", "payload", cwd=source)
    with zipfile.ZipFile(box / "w.zip", "w") as archive:
        archive.write(box / "data.tar", "data.tar")
    outcome = run_extract(box / "w.zip", output_dir=tmp_path / "pick", only=("data.tar",))
    assert outcome.ok, outcome.error
    assert outcome.output.name == "data.tar" and outcome.output.is_file()


def test_selection_inside_a_byte_split(source, box, tmp_path):
    blob(source)
    sh("7zz", "a", "-tzip", box / "w.zip", "payload", cwd=source)
    byte_split(box / "w.zip")
    outcome = run_extract(box / "w.zip.001", output_dir=tmp_path / "pick", only=("payload/sub/b.txt",))
    assert outcome.ok, outcome.error
    assert outcome.output.read_text() == "beta\n"


def test_selection_inside_a_tar_wrapped_in_lz4(source, box, tmp_path):
    pipe(f"tar cf - payload | lz4 -q - '{box / 'x.tar.lz4'}'", source)
    outcome = run_extract(box / "x.tar.lz4", output_dir=tmp_path / "pick", only=("payload/a.txt",))
    assert outcome.ok, outcome.error
    assert outcome.output.read_text() == "alpha\n"


def test_selection_never_follows_a_symlinked_parent(box, tmp_path):
    victim = tmp_path / "Documents"
    victim.mkdir()
    (victim / "tax.pdf").write_text("mine")

    def build(archive):
        add_link(archive, "docs", str(victim))
        add_file(archive, "other.txt")

    tar_with(box / "t.tar", build)
    sh("gzip", box / "t.tar")
    outcome = run_extract(box / "t.tar.gz", output_dir=tmp_path / "pick", only=("docs/tax.pdf",))
    assert not outcome.ok
    assert (victim / "tax.pdf").read_text() == "mine"


def test_quarantine_follows_the_archive(box):
    archive = zip_with(box / "m.zip", {"payload/a.txt": "1", "payload/b.txt": "2"})
    value = "0081;5f000000;Safari;"
    sh("xattr", "-w", "com.apple.quarantine", value, archive)
    outcome = run_extract(archive)
    read = subprocess.run(
        ["xattr", "-p", "com.apple.quarantine", outcome.output / "a.txt"], capture_output=True, text=True
    )
    assert read.stdout.strip() == value


def test_interrupt_leaves_nothing_behind(source, box):
    blob(source, 2_000_000)
    sh("7zz", "a", box / "x.7z", "payload", cwd=source)

    def interrupt(_percent):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_extract(box / "x.7z", on_tick=interrupt)
    assert no_leftovers(box)


def test_progress_reports_ticks(box):
    seen = []
    outcome = run_extract(zip_with(box / "m.zip", {"a.txt": "1"}), on_tick=seen.append)
    assert outcome.ok


def test_outcome_reports_totals(box):
    outcome = run_extract(zip_with(box / "m.zip", {"p/a": "12345", "p/b": "123"}))
    assert (outcome.files, outcome.total_bytes) == (2, 8)
    assert outcome.seconds >= 0
