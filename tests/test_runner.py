import os
import sys

import pytest

from ex.backends import PROGRESS_PERCENT
from ex.runner import RunResult, run


def test_captures_output_and_exit_code():
    result = run(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"])
    assert result.code == 3 and "out" in result.output and "err" in result.output


def test_reports_percent_from_backspace_style_progress():
    seen = []
    run(
        ["/bin/sh", "-c", r"printf '  5%% 1 - a\b\b\b 42%% 2 - b'; sleep 0.3"],
        progress_style=PROGRESS_PERCENT,
        on_tick=seen.append,
    )
    assert 42 in seen


def test_percent_inside_a_file_name_is_ignored():
    seen = []
    run(["/bin/sh", "-c", r"printf '100%%.txt'; sleep 0.3"], progress_style=PROGRESS_PERCENT, on_tick=seen.append)
    assert 100 not in seen


def test_children_have_no_controlling_terminal():
    result = run(["/bin/sh", "-c", ": < /dev/tty && echo HAS_TTY || echo NO_TTY"])
    assert "NO_TTY" in result.output


def test_children_never_read_our_stdin():
    assert run(["/bin/cat"]).ok


def test_children_get_a_utf8_locale():
    assert "UTF-8" in run(["/bin/sh", "-c", 'echo "$LC_ALL"']).output


def test_interrupt_kills_the_child():
    def interrupt(_percent):
        raise KeyboardInterrupt

    marker_script = "trap '' INT; sleep 30"
    with pytest.raises(KeyboardInterrupt):
        run(["/bin/sh", "-c", marker_script], on_tick=interrupt)


@pytest.mark.parametrize(
    "output",
    [
        "ERROR: Wrong password : a.txt",
        "Cannot open encrypted archive. Wrong password?",
        "a.txt  (6 B)... Failed! (Missing or wrong password)",
        "Incorrect password for a.txt",
        "CRC failed in a.txt (password incorrect ?)",
        "a.txt: Too many incorrect passphrases",
        "bsdtar: The archive header is encrypted, but currently not supported",
    ],
)
def test_recognises_every_tools_password_complaint(output):
    assert RunResult(1, output).needs_password is True


@pytest.mark.parametrize(
    "output",
    [
        "ERRORS:\nUnexpected end of archive",
        "ERROR: CRC Failed : a/b.txt",
        "ERROR: Data Error : a.txt",
        "bsdtar: Error opening archive: truncated gzip input",
        "ERROR: Bad archive zero.rar",
        "ERRORS:\nIs not archive",
        "Open ERROR: Cannot open the file as [7z] archive",
        "bsdtar: Error opening archive: Unrecognized archive format",
    ],
)
def test_recognises_damaged_archives(output):
    assert RunResult(2, output).looks_damaged is True


def test_a_missing_codec_is_not_called_damage():
    assert RunResult(2, "ERROR: Unsupported Method : a.txt").looks_damaged is False


def test_a_successful_run_is_never_damaged():
    assert RunResult(0, "CRC Failed").looks_damaged is False


def test_a_file_named_passphrase_is_not_a_password_complaint():
    assert RunResult(2, "ERROR: CRC Failed : passphrase.txt").needs_password is False


def test_without_removes_paths_from_classification():
    result = RunResult(2, "Extracting /x/corrupt/passphrase-backup.zip\nodd failure").without("/x/corrupt/passphrase-backup.zip")
    assert result.looks_damaged is False and "passphrase" not in result.output


@pytest.mark.parametrize(
    "output,expected",
    [
        ("ERRORS:\nUnexpected end of archive", True),
        ("ERROR: CRC Failed : a", True),
        ("Headers Error", True),
        ("bsdtar: Error opening archive: Unrecognized archive format", False),
        ("ERRORS:\nIs not archive", False),
    ],
)
def test_corruption_is_distinct_from_not_recognising_the_format(output, expected):
    assert RunResult(2, output).is_corrupt is expected


def test_a_successful_run_never_needs_a_password():
    assert RunResult(0, "wrong password").needs_password is False


def test_unrelated_failure_does_not_need_a_password():
    assert RunResult(2, "ERROR: Unsupported Method : a.txt").needs_password is False


def test_error_line_prefers_the_cause_over_the_summary():
    output = "Scanning\nERROR: Data Error : a.txt\n\nSub items Errors: 1\nArchives with Errors: 1\n"
    assert RunResult(2, output).first_error_line() == "ERROR: Data Error : a.txt"


def test_error_line_falls_back_to_the_last_line():
    assert RunResult(1, "something\nodd happened\n").first_error_line() == "odd happened"


def test_error_line_handles_silence():
    assert RunResult(1, "").first_error_line() != ""
