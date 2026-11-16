import os

from ex import stage


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_create_makes_a_hidden_sibling_following_the_umask(tmp_path):
    made = stage.create(tmp_path)
    assert made.parent == tmp_path and made.name.startswith(".")
    assert made.stat().st_mode & 0o777 == 0o777 & ~current_umask()


def current_umask():
    value = os.umask(0)
    os.umask(value)
    return value


def test_discard_removes_read_only_directories(tmp_path):
    root = stage.create(tmp_path)
    locked = root / "locked"
    locked.mkdir()
    (locked / "f").write_text("x")
    locked.chmod(0o500)
    stage.discard(root)
    assert not root.exists()


def test_discard_is_best_effort(tmp_path, monkeypatch):
    root = stage.create(tmp_path)
    (root / "d").mkdir()

    def refuse(*_args):
        raise PermissionError("immutable")

    monkeypatch.setattr(stage.os, "chmod", refuse)
    stage.discard(root)
    assert not root.exists()


def test_reset_leaves_an_empty_directory(tmp_path):
    root = stage.create(tmp_path)
    (root / "partial").write_text("x")
    stage.reset(root)
    assert root.is_dir() and list(root.iterdir()) == []


def test_junk_is_removed_at_the_root(tmp_path):
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / ".DS_Store").write_text("x")
    (tmp_path / "real.txt").write_text("x")
    stage.remove_junk(tmp_path)
    assert tree(tmp_path) == ["real.txt"]


def test_junk_is_removed_inside_a_lone_volume_folder(tmp_path):
    volume = tmp_path / "Installer"
    (volume / ".HFS+ Private Directory Data\r").mkdir(parents=True)
    (volume / ".Trashes").mkdir()
    (volume / "app.txt").write_text("x")
    stage.remove_junk(tmp_path)
    assert tree(tmp_path) == ["Installer", "Installer/app.txt"]


def test_deep_files_that_look_like_junk_are_left_alone(tmp_path):
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (deep / ".DS_Store").write_text("x")
    (tmp_path / "other").write_text("x")
    stage.remove_junk(tmp_path)
    assert "a/b/.DS_Store" in tree(tmp_path)


def test_symlinks_leaving_the_tree_are_dropped_and_reported(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "keep.txt").write_text("x")
    (root / "abs").symlink_to("/etc/passwd")
    (root / "sub" / "up").symlink_to("../../outside")
    (root / "inside").symlink_to("keep.txt")
    (root / "sub" / "sibling").symlink_to("../keep.txt")
    dropped = stage.prune_escaping_symlinks(root)
    assert sorted(dropped) == ["abs", "sub/up"]
    assert sorted(tree(root)) == ["inside", "keep.txt", "sub", "sub/sibling"]


def test_symlink_chains_cannot_hide_an_escape(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "toroot").symlink_to("..")
    (root / "sub" / "sneaky").symlink_to("toroot/..")
    (root / "second").write_text("x")
    dropped = stage.prune_escaping_symlinks(root)
    assert "sub/sneaky" in dropped and "sub/toroot" not in dropped


def test_links_are_judged_against_the_folder_that_will_be_promoted(tmp_path):
    root = tmp_path / "root"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "leak").symlink_to("../secret.txt")
    (root / "pkg" / "up").symlink_to("..")
    (root / "pkg" / "self").symlink_to(".")
    assert sorted(stage.prune_escaping_symlinks(root)) == ["pkg/leak", "pkg/up"]


def test_lone_symlink_is_dropped(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "x").symlink_to("secret.txt")
    assert stage.prune_escaping_symlinks(root) == ("x",)


def test_links_inside_read_only_folders_are_still_removed(tmp_path):
    root = tmp_path / "root"
    locked = root / "pkg"
    locked.mkdir(parents=True)
    (locked / "bad").symlink_to("/etc/passwd")
    locked.chmod(0o555)
    assert stage.prune_escaping_symlinks(root) == ("pkg/bad",)
    assert locked.stat().st_mode & 0o777 == 0o555


def test_links_inside_unreadable_folders_are_still_found(tmp_path):
    root = tmp_path / "root"
    locked = root / "pkg"
    locked.mkdir(parents=True)
    (locked / "bad").symlink_to("/etc/passwd")
    (root / "other").write_text("x")
    locked.chmod(0)
    assert stage.prune_escaping_symlinks(root) == ("pkg/bad",)


def test_junk_inside_a_read_only_folder_is_removed(tmp_path):
    locked = tmp_path / "pkg"
    locked.mkdir()
    (locked / ".DS_Store").write_text("x")
    (locked / "a").write_text("x")
    locked.chmod(0o555)
    stage.remove_junk(tmp_path)
    assert not (locked / ".DS_Store").exists()
    assert locked.stat().st_mode & 0o777 == 0o555


def test_sole_file_finds_only_a_lone_regular_file(tmp_path):
    assert stage.sole_file(tmp_path) is None
    (tmp_path / "a").write_text("x")
    assert stage.sole_file(tmp_path).name == "a"
    (tmp_path / "b").write_text("x")
    assert stage.sole_file(tmp_path) is None


def test_sole_file_ignores_a_symlink(tmp_path):
    (tmp_path / "a").symlink_to("/etc/hosts")
    assert stage.sole_file(tmp_path) is None


def test_measure_counts_a_directory(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f").write_bytes(b"12345")
    (tmp_path / "top").write_bytes(b"123")
    assert stage.measure(tmp_path) == (2, 8)


def test_measure_counts_a_single_file(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"1234")
    assert stage.measure(path) == (1, 4)


def test_measure_does_not_follow_symlinks(tmp_path):
    (tmp_path / "big").symlink_to("/bin/sh")
    count, size = stage.measure(tmp_path)
    assert count == 1 and size < 4096


def test_unique_path_is_untouched_when_free(tmp_path):
    assert stage.unique_path(tmp_path / "x", keep_suffix=False) == tmp_path / "x"


def test_unique_path_numbers_folders_whole(tmp_path):
    (tmp_path / "data.v2").mkdir()
    assert stage.unique_path(tmp_path / "data.v2", keep_suffix=False).name == "data.v2 (2)"


def test_unique_path_keeps_a_file_extension(tmp_path):
    (tmp_path / "a.pdf").write_text("x")
    (tmp_path / "a (2).pdf").write_text("x")
    assert stage.unique_path(tmp_path / "a.pdf", keep_suffix=True).name == "a (3).pdf"


def test_unique_path_counts_dangling_symlinks_as_taken(tmp_path):
    (tmp_path / "x").symlink_to("/nonexistent/target")
    assert stage.unique_path(tmp_path / "x", keep_suffix=False).name == "x (2)"


def build(tmp_path, *names):
    root = stage.create(tmp_path)
    for name in names:
        (root / name).write_text("x")
    return root


def test_promote_moves_a_lone_entry_up(tmp_path):
    root = build(tmp_path, "only.txt")
    result = stage.promote(root, tmp_path, "archive")
    assert result == tmp_path / "only.txt" and not root.exists()


def test_promote_keeps_a_lone_directory_name(tmp_path):
    root = stage.create(tmp_path)
    (root / "project").mkdir()
    assert stage.promote(root, tmp_path, "archive") == tmp_path / "project"


def test_promote_handles_a_read_only_folder_and_keeps_its_mode(tmp_path):
    root = stage.create(tmp_path)
    (root / "pkg").mkdir()
    (root / "pkg").chmod(0o555)
    result = stage.promote(root, tmp_path, "archive")
    assert result == tmp_path / "pkg" and result.stat().st_mode & 0o777 == 0o555


def test_promote_wraps_many_entries_in_the_archive_name(tmp_path):
    root = build(tmp_path, "a", "b")
    result = stage.promote(root, tmp_path, "archive")
    assert result == tmp_path / "archive" and tree(result) == ["a", "b"]


def test_promote_wraps_a_lone_hidden_entry_so_it_stays_visible(tmp_path):
    root = build(tmp_path, ".config")
    assert stage.promote(root, tmp_path, "archive") == tmp_path / "archive"


def test_promote_never_replaces_existing_data(tmp_path):
    (tmp_path / "only.txt").write_text("precious")
    root = build(tmp_path, "only.txt")
    result = stage.promote(root, tmp_path, "archive")
    assert result.name == "only (2).txt"
    assert (tmp_path / "only.txt").read_text() == "precious"
