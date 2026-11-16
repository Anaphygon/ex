from pathlib import Path

import pytest

from ex import backends
from ex.backends import extract_argv, missing_binaries, resolve


def only(monkeypatch, *installed):
    monkeypatch.setattr(
        backends.shutil, "which", lambda name, path=None: f"/bin/{name}" if name in installed else None
    )


ALL_TOOLS = ("7zz", "bsdtar", "unar", "unrar", "lz4", "brotli", "gzip")


def names(candidates):
    return [candidate.name for candidate in candidates]


def test_zip_prefers_7z_for_progress_and_aes(monkeypatch):
    only(monkeypatch, *ALL_TOOLS)
    assert names(resolve("zip"))[0] == "7z"


def test_rar_prefers_the_official_tool(monkeypatch):
    only(monkeypatch, *ALL_TOOLS)
    assert names(resolve("rar5"))[0] == "unrar"


def test_uninstalled_backends_are_skipped(monkeypatch):
    only(monkeypatch, "unar")
    assert names(resolve("rar5")) == ["unar"]


def test_prefer_moves_a_backend_to_the_front_once(monkeypatch):
    only(monkeypatch, *ALL_TOOLS)
    assert names(resolve("zip", prefer=("unar",))) == ["unar", "7z", "bsdtar"]


def test_passwords_drop_backends_that_cannot_use_one(monkeypatch):
    only(monkeypatch, *ALL_TOOLS)
    assert "bsdtar" not in names(resolve("zip", want_password=True))


def test_unknown_formats_still_get_a_chance(monkeypatch):
    only(monkeypatch, *ALL_TOOLS)
    assert names(resolve(None)) == ["7z", "unar"]


def test_helper_needs_the_binary_of_that_format(monkeypatch):
    only(monkeypatch, "lz4")
    assert names(resolve("lz4")) == ["helper"]
    assert names(resolve("brotli")) == []


def test_missing_binaries_name_what_to_install(monkeypatch):
    only(monkeypatch)
    assert missing_binaries("brotli") == ("brotli",)
    assert "7zz" in missing_binaries("dmg")


def test_binaries_are_searched_beyond_the_finder_path(monkeypatch):
    seen = {}

    def which(name, path=None):
        seen["path"] = path
        return None

    monkeypatch.setattr(backends.shutil, "which", which)
    resolve("zip")
    assert "/opt/homebrew/bin" in seen["path"].split(":")


ARCHIVE, DEST = Path("/a/x.zip"), Path("/d")


def argv_for(monkeypatch, format_key, password=None):
    only(monkeypatch, *ALL_TOOLS)
    return extract_argv(resolve(format_key)[0], ARCHIVE, DEST, password, format_key)


def test_7z_without_password_never_prompts_and_skips_alternate_streams(monkeypatch):
    argv = argv_for(monkeypatch, "zip")
    assert "-p" in argv and "-sns-" in argv and argv[-2:] == ["--", str(ARCHIVE)]


def test_7z_passes_the_password(monkeypatch):
    assert "-psecret" in argv_for(monkeypatch, "zip", "secret")


def test_split_format_forces_the_split_handler(monkeypatch):
    assert "-tSplit" in argv_for(monkeypatch, "split")


def test_unrar_without_password_disables_the_prompt(monkeypatch):
    assert "-p-" in argv_for(monkeypatch, "rar5")


def test_helper_writes_the_stem_through_a_shell_redirect(monkeypatch):
    only(monkeypatch, *ALL_TOOLS)
    argv = extract_argv(resolve("lz4")[0], Path("/a/note.txt.lz4"), DEST, None, "lz4")
    assert argv[0] == "/bin/sh" and argv[-3:] == ["/bin/lz4", "/a/note.txt.lz4", "/d/note.txt"]


def test_unknown_backend_is_a_programming_error():
    fake = backends.ResolvedBackend(backends.Backend("nope"), "/bin/nope")
    with pytest.raises(ValueError):
        extract_argv(fake, ARCHIVE, DEST, None, "zip")
