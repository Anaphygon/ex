"""Run an extractor as a child process while keeping the progress line alive."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from .backends import PROGRESS_NONE, PROGRESS_PERCENT

READ_BYTES = 1 << 16
TICK_SECONDS = 0.08
DRAIN_TIMEOUT = 2.0
STOP_TIMEOUT = 5.0
UTF8_LOCALE = "en_US.UTF-8"

# The look-ahead keeps "100%.txt" in a progress line from reading as a number.
_PERCENT = re.compile(rb"(\d{1,3})%(?=[\s\x08]|$)")

_PASSWORD_HINTS = (
    "wrong password",  # 7z, unar
    "incorrect password",  # unrar
    "password incorrect",  # unrar, older RAR4 wording
    "incorrect passphrase",  # bsdtar on an encrypted zip
    "enter passphrase",  # bsdtar on an encrypted zip
    "content is encrypted",  # bsdtar on an encrypted 7z
    "header is encrypted",  # bsdtar on an encrypted 7z
    "requires a password",  # lsar
)

# The file is definitely bad. A more lenient tool might still exit 0 on it,
# having quietly unpacked only what survived, so no fallback is tried.
_CORRUPTION_HINTS = (
    "unexpected end",
    "truncated",
    "crc failed",
    "data error",
    "headers error",
    "bad archive",
    "corrupt",
)
# This tool does not recognise the file; another one might.
_UNRECOGNIZED_HINTS = (
    "is not archive",
    "cannot open the file",
    "unrecognized archive format",
)

_ERROR_WORDS = (
    "error",
    "cannot",
    "can't",
    "unsupported",
    "unrecognized",
    "corrupt",
    "truncated",
    "failed",
    "unexpected end",
)
# 7-Zip's closing tally mentions errors without saying what went wrong.
_ERROR_SUMMARIES = ("sub items errors", "archives with errors", "errors:")


@dataclass(frozen=True)
class RunResult:
    code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def needs_password(self) -> bool:
        lowered = self.output.lower()
        return not self.ok and any(hint in lowered for hint in _PASSWORD_HINTS)

    @property
    def is_corrupt(self) -> bool:
        lowered = self.output.lower()
        return not self.ok and any(hint in lowered for hint in _CORRUPTION_HINTS)

    @property
    def looks_damaged(self) -> bool:
        lowered = self.output.lower()
        return self.is_corrupt or (not self.ok and any(hint in lowered for hint in _UNRECOGNIZED_HINTS))

    def without(self, *texts: str) -> RunResult:
        """A copy with ``texts`` blanked, so a path cannot pass for a diagnosis.

        Classification is substring matching, and tools echo paths: an archive
        called passphrase-backup.zip must not look like a password problem.
        """
        output = self.output
        for text in texts:
            output = output.replace(text, "archive")
        return RunResult(self.code, output)

    def first_error_line(self) -> str:
        """The most useful single line to show a human."""
        lines = [line.strip() for line in re.split(r"[\r\n\x08]+", self.output) if line.strip()]
        for line in lines:
            lowered = line.lower()
            if lowered.startswith(_ERROR_SUMMARIES):
                continue
            if any(word in lowered for word in _ERROR_WORDS):
                return line
        return lines[-1] if lines else "the tool exited without a message"


def _last_percent(chunk: bytes) -> int | None:
    matches = _PERCENT.findall(chunk)
    if not matches:
        return None
    value = int(matches[-1])
    return value if value <= 100 else None


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _child_env() -> dict[str, str]:
    return {**os.environ, "LC_ALL": UTF8_LOCALE, "LANG": UTF8_LOCALE}


def capture(argv: Sequence[str]) -> tuple[RunResult, str]:
    """Run ``argv`` to completion; return the result plus stdout on its own.

    For tools whose stdout is data (lsar's JSON), which a merged stream
    would corrupt with warnings. Same isolation as ``run``.
    """
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=_child_env(),
        check=False,
    )
    stdout = completed.stdout.decode("utf-8", "replace")
    stderr = completed.stderr.decode("utf-8", "replace")
    return RunResult(completed.returncode, f"{stdout}\n{stderr}"), stdout


def run(
    argv: Sequence[str],
    *,
    progress_style: str = PROGRESS_NONE,
    on_tick: Callable[[int | None], None] | None = None,
) -> RunResult:
    """Execute ``argv``, merging stderr into stdout.

    The child gets its own session, so it has no controlling terminal: left
    alone, bsdtar opens /dev/tty and prompts for a passphrase on its own.
    ``on_tick`` is called roughly every 80 ms with the latest percentage the
    backend reported, or None when it reports none.
    """
    process = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=_child_env(),
    )
    chunks: list[bytes] = []
    latest: dict[str, int | None] = {"percent": None}

    def drain() -> None:
        fileno = process.stdout.fileno()
        while data := os.read(fileno, READ_BYTES):
            chunks.append(data)
            if progress_style == PROGRESS_PERCENT and (percent := _last_percent(data)) is not None:
                latest["percent"] = percent

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            if on_tick:
                on_tick(latest["percent"])
            time.sleep(TICK_SECONDS)
    except BaseException:
        _stop(process)
        raise
    finally:
        reader.join(timeout=DRAIN_TIMEOUT)
        process.stdout.close()

    return RunResult(process.returncode, b"".join(chunks).decode("utf-8", "replace"))
