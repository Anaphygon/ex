import subprocess
from types import SimpleNamespace

import pytest

from ex import macos


class Recorder:
    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self.result = SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        return self.result


@pytest.fixture
def recorder(monkeypatch):
    fake = Recorder()
    monkeypatch.setattr(macos.subprocess, "run", fake)
    return fake


def test_quarantine_round_trip_on_real_files(tmp_path):
    archive = tmp_path / "a.zip"
    archive.write_text("x")
    folder = tmp_path / "out"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "f").write_text("x")
    value = "0081;5f000000;Safari;"
    subprocess.run(["xattr", "-w", macos.QUARANTINE_ATTR, value, str(archive)], check=True)
    assert macos.read_quarantine(archive) == value
    assert macos.apply_quarantine(folder, value) is True
    assert macos.read_quarantine(folder / "sub" / "f") == value


def test_read_only_entries_are_quarantined_too_and_keep_their_mode(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "tool").write_text("x")
    (folder / "tool").chmod(0o555)
    (folder / "plain").write_text("x")
    locked = folder / "locked"
    locked.mkdir()
    (locked / "inner").write_text("x")
    (locked / "inner").chmod(0o444)
    locked.chmod(0o555)
    value = "0081;5f000000;Safari;"
    assert macos.apply_quarantine(folder, value) is True
    assert macos.read_quarantine(folder / "tool") == value
    assert macos.read_quarantine(locked / "inner") == value
    assert (folder / "tool").stat().st_mode & 0o777 == 0o555
    assert locked.stat().st_mode & 0o777 == 0o555


def test_a_single_read_only_file_is_quarantined(tmp_path):
    path = tmp_path / "tool"
    path.write_text("x")
    path.chmod(0o555)
    value = "0081;5f000000;Safari;"
    assert macos.apply_quarantine(path, value) is True
    assert macos.read_quarantine(path) == value


def test_unquarantined_file_reads_none(tmp_path):
    path = tmp_path / "a"
    path.write_text("x")
    assert macos.read_quarantine(path) is None


def test_user_text_never_reaches_the_script_source(recorder):
    hostile = 'x" & (do shell script "touch /tmp/pwned") & "'
    macos.notify("Ex", hostile)
    argv = recorder.calls[0]
    separator = argv.index("--")
    assert hostile not in " ".join(argv[:separator]) and argv[separator + 1:] == ["Ex", hostile]


def test_password_prompt_returns_the_exact_answer(monkeypatch):
    fake = Recorder(stdout=" pass word \n")
    monkeypatch.setattr(macos.subprocess, "run", fake)
    assert macos.ask_password("Password?") == " pass word "


def test_password_prompt_cancel_is_none(monkeypatch):
    monkeypatch.setattr(macos.subprocess, "run", Recorder(returncode=1))
    assert macos.ask_password("Password?") is None


def test_empty_password_answer_is_none(monkeypatch):
    monkeypatch.setattr(macos.subprocess, "run", Recorder(stdout="\n"))
    assert macos.ask_password("Password?") is None


def test_alert_passes_title_and_message_as_arguments(recorder):
    macos.alert("Gagal", "a.zip: rusak")
    assert recorder.calls[0][-2:] == ["Gagal", "a.zip: rusak"]


def test_reveal_selects_in_finder(recorder, tmp_path):
    macos.reveal(tmp_path / "x")
    assert recorder.calls[0] == ["/usr/bin/open", "-R", str(tmp_path / "x")]


@pytest.mark.parametrize("script", [macos.NOTIFY_SCRIPT, macos.ASK_PASSWORD_SCRIPT, macos.ALERT_SCRIPT])
def test_applescript_sources_compile(tmp_path, script):
    args = ["/usr/bin/osacompile", "-o", str(tmp_path / "out.scpt")]
    for line in script:
        args += ["-e", line]
    subprocess.run(args, check=True, capture_output=True)
