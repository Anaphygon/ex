import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from ex import cli, frontends, macos

LAUNCHER = Path(__file__).resolve().parent.parent / "bin" / "ex-extract"


def zip_with(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_extracts_a_file_and_reports_success(tmp_path, capsys):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    assert cli.main([str(archive)]) == 0
    assert (tmp_path / "p" / "a.txt").exists()
    assert "✓" in capsys.readouterr().out


def test_failure_sets_the_exit_code(tmp_path, capsys):
    assert cli.main([str(tmp_path / "ghost.zip")]) == 1
    assert "✗" in capsys.readouterr().out


def test_mixed_batch_reports_both(tmp_path, capsys):
    good = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    assert cli.main([str(good), str(tmp_path / "ghost.zip")]) == 1
    out = capsys.readouterr().out
    assert "1 succeeded" in out and "1 failed" in out


def test_output_flag(tmp_path, capsys):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    assert cli.main([str(archive), "-o", str(tmp_path / "there")]) == 0
    assert (tmp_path / "there" / "p" / "a.txt").exists()


def test_selecting_every_part_extracts_once(tmp_path, capsys):
    data = zip_with(tmp_path / "w.zip", {"p/a.txt": "x" * 10})
    raw = data.read_bytes()
    data.unlink()
    middle = len(raw) // 2
    (tmp_path / "w.zip.001").write_bytes(raw[:middle])
    (tmp_path / "w.zip.002").write_bytes(raw[middle:])
    assert cli.main([str(tmp_path / "w.zip.001"), str(tmp_path / "w.zip.002")]) == 0
    assert (tmp_path / "p" / "a.txt").exists()
    assert not (tmp_path / "p (2)").exists()


def interactive(monkeypatch, answer):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *_: answer)


@pytest.fixture
def downloads(tmp_path):
    zip_with(tmp_path / "one.zip", {"one/a": "1"})
    zip_with(tmp_path / "two.zip", {"two/a": "1"})
    zip_with(tmp_path / "report.docx", {"word/a": "1"})
    return tmp_path


def test_directory_scan_asks_then_extracts_real_archives_only(downloads, monkeypatch, capsys):
    interactive(monkeypatch, "y")
    assert cli.main([str(downloads)]) == 0
    assert (downloads / "one").is_dir() and (downloads / "two").is_dir()
    assert not (downloads / "word").exists()


def test_directory_scan_can_be_declined(downloads, monkeypatch, capsys):
    interactive(monkeypatch, "n")
    assert cli.main([str(downloads)]) == 0
    assert not (downloads / "one").exists()


def test_no_arguments_scans_the_current_directory(downloads, monkeypatch, capsys):
    interactive(monkeypatch, "y")
    monkeypatch.chdir(downloads)
    assert cli.main([]) == 0
    assert (downloads / "one").is_dir()


def test_directory_scan_refuses_without_a_terminal(downloads, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.main([str(downloads)]) == 0
    assert not (downloads / "one").exists()


def test_empty_directory_says_so(tmp_path, capsys):
    assert cli.main([str(tmp_path)]) == 0
    assert "archive" in capsys.readouterr().out.lower()


def test_scan_counts_a_split_set_once(tmp_path, monkeypatch, capsys):
    (tmp_path / "s.7z.001").touch()
    (tmp_path / "s.7z.002").touch()
    interactive(monkeypatch, "n")
    cli.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "s.7z.001" in out and "s.7z.002" not in out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--version"])
    assert stopped.value.code == 0


def test_interrupt_exits_130(tmp_path, monkeypatch, capsys):
    archive = zip_with(tmp_path / "m.zip", {"a": "1"})

    def boom(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "extract", boom)
    assert cli.main([str(archive)]) == 130


def test_unreadable_folder_is_reported_not_raised(tmp_path, capsys):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert cli.main([str(locked)]) == 1
    finally:
        locked.chmod(0o700)
    assert "✗" in capsys.readouterr().out


def test_unexpected_crash_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    archive = zip_with(tmp_path / "m.zip", {"a": "1"})

    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "extract", boom)
    assert cli.main([str(archive)]) == 1
    assert "kaboom" in capsys.readouterr().out


def test_terminal_prompt_without_a_tty_gives_up(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert frontends.TerminalFront().ask_password(Path("x.zip"), False) is None


def test_terminal_prompt_reads_hidden_input(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(frontends.getpass, "getpass", lambda *_: "typed")
    front = frontends.TerminalFront()
    assert front.ask_password(Path("x.zip"), False) == "typed"


def test_terminal_prompt_treats_blank_as_cancel(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(frontends.getpass, "getpass", lambda *_: "")
    assert frontends.TerminalFront().ask_password(Path("x.zip"), True) is None


@pytest.fixture
def gui(monkeypatch):
    calls = {"notify": [], "alert": [], "reveal": []}
    monkeypatch.setattr(macos, "notify", lambda title, text: calls["notify"].append((title, text)))
    monkeypatch.setattr(macos, "alert", lambda title, text: calls["alert"].append((title, text)))
    monkeypatch.setattr(macos, "reveal", lambda path: calls["reveal"].append(path))
    return calls


def test_gui_success_notifies(tmp_path, gui):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    assert cli.main(["--gui", str(archive)]) == 0
    assert len(gui["notify"]) == 1 and "p" in gui["notify"][0][1]
    assert gui["alert"] == [] and gui["reveal"] == []


def test_gui_reveal_selects_the_result(tmp_path, gui):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    cli.main(["--gui", "--reveal", str(archive)])
    assert gui["reveal"] == [tmp_path / "p"]


def test_gui_failure_raises_an_alert(tmp_path, gui):
    (tmp_path / "notes.txt").write_text("plain words here")
    assert cli.main(["--gui", str(tmp_path / "notes.txt")]) == 1
    assert len(gui["alert"]) == 1 and "notes.txt" in gui["alert"][0][1]


def test_gui_batch_summarises(tmp_path, gui):
    one = zip_with(tmp_path / "a.zip", {"a/x": "1"})
    two = zip_with(tmp_path / "b.zip", {"b/x": "1"})
    cli.main(["--gui", "--reveal", str(one), str(two)])
    assert len(gui["notify"]) == 1 and "2" in gui["notify"][0][1]
    assert gui["reveal"] == []


def test_gui_announces_only_big_archives(tmp_path, gui, monkeypatch):
    monkeypatch.setattr(frontends, "NOTIFY_START_MIN_BYTES", 1)
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    cli.main(["--gui", str(archive)])
    assert len(gui["notify"]) == 2


def test_gui_skips_folders_without_asking(tmp_path, gui):
    zip_with(tmp_path / "m.zip", {"p/a": "1"})
    assert cli.main(["--gui", str(tmp_path)]) == 0
    assert not (tmp_path / "p").exists()
    assert len(gui["alert"]) == 1


def test_gui_crash_is_shown_because_output_is_discarded(tmp_path, gui, monkeypatch):
    archive = zip_with(tmp_path / "m.zip", {"a": "1"})

    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "extract", boom)
    assert cli.main(["--gui", str(archive)]) == 1
    assert "kaboom" in gui["alert"][0][1]


def test_gui_password_dialog_is_used(tmp_path, gui, monkeypatch):
    archive = tmp_path / "e.7z"
    source = tmp_path / "s.txt"
    source.write_text("x")
    subprocess.run(["7zz", "a", "-psecret", str(archive), str(source)], check=True, capture_output=True)
    source.unlink()
    monkeypatch.setattr(macos, "ask_password", lambda prompt: "secret")
    assert cli.main(["--gui", str(archive)]) == 0
    assert (tmp_path / "s.txt").exists()


def test_launcher_works_with_finders_bare_environment(tmp_path):
    archive = zip_with(tmp_path / "m.zip", {"payload/日本語 ファイル.txt": "1"})
    completed = subprocess.run(
        [str(LAUNCHER), str(archive)],
        env={"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (tmp_path / "payload" / "日本語 ファイル.txt").exists()


def test_launcher_ignores_modules_planted_in_the_working_directory(tmp_path):
    (tmp_path / "zipfile.py").write_text("raise SystemExit('planted module ran')")
    (tmp_path / "ex.py").write_text("raise SystemExit('planted module ran')")
    archive = zip_with(tmp_path / "m.zip", {"payload/a.txt": "1"})
    completed = subprocess.run([str(LAUNCHER), str(archive)], cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
