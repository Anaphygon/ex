import json
import os
import signal
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "bin" / "ex-engine"
PASSWORD = "secret"


def engine(*args, stdin_lines=(), cwd=None):
    completed = subprocess.run(
        [str(ENGINE), *map(str, args)],
        input="".join(json.dumps(line) + "\n" for line in stdin_lines),
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode, events


def final(events):
    return events[-1]


def zip_with(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_list_reports_entries(tmp_path):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "12345", "p/q/b.txt": "1"})
    code, events = engine("list", archive)
    assert code == 0
    done = final(events)
    assert done["type"] == "listing" and done["label"] == "zip"
    files = {e["path"]: e for e in done["entries"] if not e["is_dir"]}
    assert files["p/a.txt"]["size"] == 5


def test_events_survive_undecodable_names(tmp_path):
    import io
    import tarfile

    with tarfile.open(tmp_path / "raw.tar", "w", encoding="utf-8", errors="surrogateescape") as archive:
        info = tarfile.TarInfo("bad\udce9.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    code, events = engine("list", tmp_path / "raw.tar")
    assert code == 0 and final(events)["type"] == "listing"


def test_list_error_is_an_event(tmp_path):
    code, events = engine("list", tmp_path / "ghost.zip")
    assert code == 1 and final(events)["type"] == "error" and final(events)["message"]


def test_extract_reports_progress_and_result(tmp_path):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1"})
    code, events = engine("extract", archive)
    assert code == 0
    assert events[0]["type"] == "progress"
    done = final(events)
    assert done["type"] == "done" and done["outputs"] == [str(tmp_path / "p")]
    assert done["files"] == 1


def test_extract_selection_into_a_folder(tmp_path):
    archive = zip_with(tmp_path / "m.zip", {"p/a.txt": "1", "p/b.txt": "2", "p/d/c.txt": "3"})
    code, events = engine("extract", archive, "--output", tmp_path / "out", "--only", "p/a.txt", "--only", "p/d")
    assert code == 0, events
    assert sorted(final(events)["outputs"]) == sorted([str(tmp_path / "out" / "a.txt"), str(tmp_path / "out" / "d")])
    assert (tmp_path / "out" / "d" / "c.txt").read_text() == "3"
    assert not (tmp_path / "out" / "b.txt").exists()


def encrypted_7z(tmp_path):
    source = tmp_path / "s"
    source.mkdir()
    (source / "f.txt").write_text("hidden")
    subprocess.run(["7zz", "a", f"-p{PASSWORD}", "-mhe=on", str(tmp_path / "e.7z"), "f.txt"], cwd=source, check=True, capture_output=True)
    return tmp_path / "e.7z"


def test_password_is_requested_over_the_protocol(tmp_path):
    archive = encrypted_7z(tmp_path)
    code, events = engine("extract", archive, "--output", tmp_path / "o", stdin_lines=[{"password": "nope"}, {"password": PASSWORD}])
    assert code == 0, events
    asks = [e for e in events if e["type"] == "password"]
    assert [a["retry"] for a in asks] == [False, True] and asks[0]["archive"] == "e.7z"
    assert (tmp_path / "o" / "f.txt").read_text() == "hidden"


def test_password_cancel_over_the_protocol(tmp_path):
    archive = encrypted_7z(tmp_path)
    code, events = engine("list", archive, stdin_lines=[{"cancel": True}])
    assert code == 1 and final(events)["type"] == "error"


def test_closed_stdin_counts_as_cancel(tmp_path):
    archive = encrypted_7z(tmp_path)
    code, events = engine("list", archive)
    assert code == 1


def test_pack_with_password_from_stdin(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    code, events = engine(
        "pack", "--format", "7z", "--name", "bundle", "--output", tmp_path, "--password-stdin", "--", tmp_path / "f.txt",
        stdin_lines=[{"password": PASSWORD}],
    )
    assert code == 0, events
    done = final(events)
    assert done["outputs"] == [str(tmp_path / "bundle.7z")]
    listed = subprocess.run(["7zz", "t", "-p" + PASSWORD, done["outputs"][0]], capture_output=True)
    assert listed.returncode == 0


def test_pack_error_is_an_event(tmp_path):
    code, events = engine("pack", "--format", "tar.gz", "--name", "x", "--output", tmp_path, "--", tmp_path / "ghost")
    assert code == 1 and final(events)["type"] == "error"


def test_formats_command_lists_pack_formats():
    code, events = engine("formats")
    assert code == 0 and "zip" in final(events)["pack"]


def test_terminate_cancels_and_cleans_up(tmp_path):
    source = tmp_path / "big"
    source.mkdir()
    (source / "blob.bin").write_bytes(os.urandom(40_000_000))
    process = subprocess.Popen(
        [str(ENGINE), "pack", "--format", "tar.xz", "--level", "9", "--name", "x", "--output", str(tmp_path / "out"), "--", str(source)],
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
    )
    (tmp_path / "out").mkdir()
    process.stdout.readline()
    time.sleep(0.3)
    process.send_signal(signal.SIGTERM)
    remaining = process.stdout.read()
    assert process.wait(timeout=20) == 130
    assert json.loads(remaining.strip().splitlines()[-1])["type"] == "cancelled"
    assert list((tmp_path / "out").iterdir()) == []


def test_unexpected_crash_still_ends_with_an_event(tmp_path):
    code, events = engine("extract", tmp_path / "m.zip", "--only", "../evil")
    assert code == 1 and final(events)["type"] == "error"
