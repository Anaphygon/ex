"""The two faces of ex: the terminal, and Finder (notifications and dialogs)."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from . import macos
from .extract import Job, Outcome
from .ui import Painter, Progress, human_bytes, human_duration, supports_color

APP_NAME = "Ex"
# Below this an extraction ends before a "working on it" banner is worth showing.
NOTIFY_START_MIN_BYTES = 50 * 1024 * 1024


def display_path(path: Path, *, is_folder: bool) -> str:
    """``./name/`` under the current directory, otherwise ``~``-relative."""
    suffix = "/" if is_folder else ""
    cwd, text = os.getcwd(), str(path)
    if text.startswith(cwd + os.sep):
        return f"./{text[len(cwd) + 1:]}{suffix}"
    home = str(Path.home())
    if text.startswith(home + os.sep):
        return f"~/{text[len(home) + 1:]}{suffix}"
    return f"{text}{suffix}"


def _describe(outcome: Outcome) -> str:
    return f"{outcome.files} files, {human_bytes(outcome.total_bytes)}"


class TerminalFront:
    def __init__(self) -> None:
        self.paint = Painter(supports_color(sys.stdout))
        self.progress: Progress | None = None

    def confirm(self, archives: list[Path]) -> bool:
        print(f"\n  Found {len(archives)} archive(s):")
        for archive in archives:
            print(f"    {archive.name}  {self.paint(human_bytes(archive.stat().st_size), 'dim')}")
        if not sys.stdin.isatty():
            print("\n  Name the files to extract them without confirming.")
            return False
        return input("\n  Extract them all? [y/N] ").strip().lower() in {"y", "yes"}

    def nothing_to_do(self) -> None:
        print("  No archives here.")

    def begin(self, job: Job) -> None:
        details = job.label if not job.size else f"{job.label}  {human_bytes(job.size)}"
        print(f"\n  {self.paint(job.archive.name, 'bold')}  {self.paint(details, 'dim')}")
        self.progress = Progress(job.archive.name, self.paint)

    def tick(self, percent: int | None) -> None:
        if self.progress:
            self.progress.tick(percent)

    def ask_password(self, archive: Path, retry: bool) -> str | None:
        if self.progress:
            self.progress.clear()
        if not sys.stdin.isatty():
            return None
        prompt = "Wrong password, try again: " if retry else f"Password for {archive.name}: "
        try:
            return getpass.getpass(f"  {prompt}") or None
        except EOFError:
            return None

    def finish(self, outcome: Outcome) -> None:
        if self.progress:
            self.progress.clear()
        if not outcome.ok:
            print(f"  {self.paint('✗', 'red')} {outcome.error}")
            return
        is_folder = outcome.output.is_dir()
        stats = f"{_describe(outcome)}  {human_duration(outcome.seconds)}"
        print(
            f"  {self.paint('✓', 'green')} "
            f"{self.paint(display_path(outcome.output, is_folder=is_folder), 'cyan')}  "
            f"{self.paint(stats, 'dim')}"
        )
        for note in outcome.notes:
            print(f"  {self.paint('!', 'yellow')} {note}")

    def summarize(self, outcomes: list[Outcome]) -> None:
        if len(outcomes) > 1:
            failed = sum(not outcome.ok for outcome in outcomes)
            print(f"\n  {len(outcomes) - failed} succeeded, {failed} failed")

    def cancelled(self) -> None:
        if self.progress:
            self.progress.clear()
        print("\n  Cancelled.")

    def fatal(self, message: str) -> None:
        if self.progress:
            self.progress.clear()
        print(f"  {self.paint('✗', 'red')} {message}")


class GuiFront:
    """For runs started from Finder, where there is no terminal to talk to."""

    def __init__(self, *, reveal: bool) -> None:
        self.reveal = reveal

    def confirm(self, archives: list[Path]) -> bool:
        macos.alert(APP_NAME, "Select the archive files, not the folder.")
        return False

    def nothing_to_do(self) -> None:
        macos.alert(APP_NAME, "There are no archives in this selection.")

    def begin(self, job: Job) -> None:
        if job.size >= NOTIFY_START_MIN_BYTES:
            macos.notify(APP_NAME, f"Extracting {job.archive.name}…")

    def tick(self, percent: int | None) -> None:
        pass

    def ask_password(self, archive: Path, retry: bool) -> str | None:
        return macos.ask_password(
            f"Wrong password for {archive.name}. Try again:"
            if retry
            else f"{archive.name} is locked. Enter the password:"
        )

    def finish(self, outcome: Outcome) -> None:
        pass

    def summarize(self, outcomes: list[Outcome]) -> None:
        succeeded = [outcome for outcome in outcomes if outcome.ok]
        failed = [outcome for outcome in outcomes if not outcome.ok]
        if failed:
            lines = "\n".join(f"{outcome.archive.name}: {outcome.error}" for outcome in failed)
            macos.alert(f"Could not extract {len(failed)} archive(s)", lines)
        if len(succeeded) == 1:
            only = succeeded[0]
            text = f"{only.output.name} — {_describe(only)}"
            macos.notify("Done", " · ".join((text, *only.notes)))
            if self.reveal and not failed:
                macos.reveal(only.output)
        elif succeeded:
            macos.notify("Done", f"Extracted {len(succeeded)} archives")

    def cancelled(self) -> None:
        macos.notify(APP_NAME, "Cancelled.")

    def fatal(self, message: str) -> None:
        macos.alert(f"{APP_NAME} failed", message)
