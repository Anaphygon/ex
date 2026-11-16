"""macOS integration: Gatekeeper metadata, notifications, dialogs, Finder.

User text always travels as ``osascript`` arguments. Interpolating a file
name into the script source would let a crafted name run AppleScript.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

QUARANTINE_ATTR = "com.apple.quarantine"
XATTR = "/usr/bin/xattr"
OSASCRIPT = "/usr/bin/osascript"
OPEN = "/usr/bin/open"

NOTIFY_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)
ASK_PASSWORD_SCRIPT = (
    "on run argv",
    "activate",
    'display dialog (item 1 of argv) with title "Ex" default answer "" with hidden answer '
    'buttons {"Cancel", "Extract"} default button "Extract" cancel button "Cancel" with icon note',
    "return text returned of result",
    "end run",
)
ALERT_SCRIPT = (
    "on run argv",
    "activate",
    "display alert (item 1 of argv) message (item 2 of argv) as critical",
    "end run",
)


def _osascript(script: tuple[str, ...], *arguments: str) -> subprocess.CompletedProcess:
    source = [flag for line in script for flag in ("-e", line)]
    return subprocess.run(
        [OSASCRIPT, *source, "--", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def read_quarantine(path: Path) -> str | None:
    """The Gatekeeper quarantine value of ``path``, if it has one."""
    completed = subprocess.run(
        [XATTR, "-p", QUARANTINE_ATTR, str(path)], capture_output=True, text=True, check=False
    )
    return (completed.stdout.strip() or None) if completed.returncode == 0 else None


def _read_only_modes(root: Path) -> dict[str, int]:
    """Everything at or under ``root`` its owner cannot write, with its mode."""
    paths = [str(root)]
    if root.is_dir() and not root.is_symlink():
        for current, directories, files in os.walk(root):
            paths += [os.path.join(current, name) for name in (*directories, *files)]
    modes = {path: os.lstat(path).st_mode for path in paths}
    return {
        path: stat.S_IMODE(mode)
        for path, mode in modes.items()
        if not stat.S_ISLNK(mode) and not mode & stat.S_IWUSR
    }


def apply_quarantine(path: Path, value: str) -> bool:
    """Mark everything under ``path`` as quarantined; True on success.

    Archive Utility does this so an app inside a downloaded zip still goes
    through Gatekeeper. The command-line extractors do not, so without this
    extracting through ``ex`` would quietly switch that protection off.

    ``xattr`` is refused on read-only files, and read-only executables are
    exactly what needs the mark, so those are opened up for the moment.
    """
    locked = _read_only_modes(path)
    for entry, mode in locked.items():
        os.chmod(entry, mode | stat.S_IWUSR)
    try:
        completed = subprocess.run(
            [XATTR, "-w", "-r", "-s", QUARANTINE_ATTR, value, str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        for entry, mode in locked.items():
            os.chmod(entry, mode)
    return completed.returncode == 0


def notify(title: str, text: str) -> None:
    _osascript(NOTIFY_SCRIPT, title, text)


def alert(title: str, text: str) -> None:
    _osascript(ALERT_SCRIPT, title, text)


def ask_password(prompt: str) -> str | None:
    """Show a hidden-input dialog; None when cancelled or left blank."""
    completed = _osascript(ASK_PASSWORD_SCRIPT, prompt)
    if completed.returncode != 0:
        return None
    return completed.stdout.removesuffix("\n") or None


def reveal(path: Path) -> None:
    """Select ``path`` in a Finder window."""
    subprocess.run([OPEN, "-R", str(path)], capture_output=True, check=False)
