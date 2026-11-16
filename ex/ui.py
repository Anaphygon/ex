"""Terminal output: colour, sizes, and the one-line live progress indicator."""

from __future__ import annotations

import os
import sys
import time

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BAR_WIDTH = 18
BYTE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
BYTE_STEP = 1024.0

_RESET = "\033[0m"
_CODES = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
}


def supports_color(stream=None) -> bool:
    """Colour only when a human on a real terminal is reading."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


class Painter:
    """Wraps text in ANSI codes, or returns it untouched when colour is off."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        prefix = "".join(_CODES.get(style, "") for style in styles)
        return f"{prefix}{text}{_RESET}"


def human_bytes(size: float) -> str:
    """``1536`` -> ``1.5 KB``. Whole numbers lose the decimal point."""
    for unit in BYTE_UNITS:
        if abs(size) < BYTE_STEP or unit == BYTE_UNITS[-1]:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}".replace(".0 ", " ")
        size /= BYTE_STEP
    return f"{size:.1f} PB"


def human_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class Progress:
    """A single self-rewriting status line on stderr.

    Silent when stderr is not a terminal, so logs and pipes stay clean.
    """

    def __init__(self, label: str, painter: Painter, stream=None) -> None:
        self.label = label
        self.painter = painter
        self.stream = stream or sys.stderr
        self._started = time.monotonic()
        self._frame = 0
        self._active = bool(getattr(self.stream, "isatty", lambda: False)())

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def tick(self, percent: int | None = None) -> None:
        if not self._active:
            return
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        spinner = self.painter(SPINNER_FRAMES[self._frame], "cyan")
        timing = self.painter(human_duration(self.elapsed), "dim")
        if percent is None:
            body = f"{self.label}  {timing}"
        else:
            filled = max(0, min(BAR_WIDTH, round(BAR_WIDTH * percent / 100)))
            bar = self.painter("█" * filled, "cyan") + self.painter("░" * (BAR_WIDTH - filled), "dim")
            body = f"{percent:3d}% {bar}  {self.label}  {timing}"
        self.stream.write(f"\r\033[2K  {spinner} {body}")
        self.stream.flush()

    def clear(self) -> None:
        if self._active:
            self.stream.write("\r\033[2K")
            self.stream.flush()
