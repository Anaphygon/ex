import io

import pytest

from ex import ui
from ex.ui import Painter, Progress, human_bytes, human_duration, supports_color


@pytest.mark.parametrize(
    "size,text",
    [(0, "0 B"), (999, "999 B"), (1536, "1.5 KB"), (432013312, "412 MB"), (1.3e9, "1.2 GB")],
)
def test_human_bytes(size, text):
    assert human_bytes(size) == text


def test_human_bytes_caps_at_the_largest_unit():
    assert human_bytes(1024.0**7).endswith("PB")


@pytest.mark.parametrize("seconds,text", [(0.4, "0.4s"), (95, "1m35s"), (3700, "1h01m")])
def test_human_duration(seconds, text):
    assert human_duration(seconds) == text


class FakeTty(io.StringIO):
    def isatty(self):
        return True


def test_painter_is_a_no_op_when_disabled():
    assert Painter(False)("x", "red") == "x"


def test_painter_wraps_when_enabled():
    painted = Painter(True)("x", "red")
    assert painted.startswith("\033[31m") and painted.endswith("\033[0m")


def test_no_color_env_wins(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert supports_color(FakeTty()) is False


def test_force_color_env(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    assert supports_color(io.StringIO()) is True


def test_pipes_get_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    assert supports_color(io.StringIO()) is False


def test_progress_is_silent_on_a_pipe():
    stream = io.StringIO()
    progress = Progress("x", Painter(False), stream)
    progress.tick(50)
    progress.clear()
    assert stream.getvalue() == ""


def test_progress_draws_a_bar_on_a_terminal():
    stream = FakeTty()
    Progress("x.zip", Painter(False), stream).tick(50)
    assert "50%" in stream.getvalue() and "x.zip" in stream.getvalue()


def test_progress_without_percent_still_animates():
    stream = FakeTty()
    Progress("x.zip", Painter(False), stream).tick(None)
    assert "x.zip" in stream.getvalue() and "%" not in stream.getvalue()


def test_progress_clear_erases_the_line():
    stream = FakeTty()
    Progress("x", Painter(False), stream).clear()
    assert "\033[2K" in stream.getvalue()
