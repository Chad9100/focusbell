import io

import pytest

from conftest import TTY
from focusbell.render import Painter, bar, bar_chart, can_encode, fmt_minutes, table, use_color


@pytest.mark.parametrize(
    "mode,tty,env,expected",
    [
        ("always", False, {}, True),
        ("never", True, {}, False),
        ("auto", True, {}, True),
        ("auto", False, {}, False),
        ("auto", True, {"NO_COLOR": "1"}, False),
        ("always", True, {"NO_COLOR": "1"}, True),
    ],
)
def test_use_color(mode, tty, env, expected):
    stream = TTY() if tty else io.StringIO()
    assert use_color(mode, stream, env) is expected


def test_painter_disabled_returns_plain_text():
    assert Painter(False)("work", "x") == "x"
    assert Painter(True)("work", "x") == "\x1b[1;31mx\x1b[0m"


def test_can_encode_detects_ascii_streams():
    ascii_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    assert not can_encode(ascii_stream, "█")
    assert can_encode(utf8_stream, "█")
    assert can_encode(io.StringIO(), "█")


def test_bar_unicode_and_ascii():
    assert bar(5, 10, 10) == "█" * 5 + "░" * 5
    assert bar(5, 10, 10, unicode=False) == "#####....."


def test_bar_small_positive_value_is_visible():
    assert bar(1, 1000, 10, unicode=False) == "#........."
    assert bar(0, 1000, 10, unicode=False) == ".........."
    assert bar(0, 0, 4, unicode=False) == "...."


def test_bar_chart_aligns_labels_and_values():
    lines = bar_chart([("Mon", 60), ("Tuesday", 30)], width=4, unicode=False)
    assert lines == ["Mon      ####   1h 00m", "Tuesday  ##..      30m"]


@pytest.mark.parametrize(
    "minutes,text", [(0, "0m"), (0.4, "0m"), (25, "25m"), (59.6, "1h 00m"), (125, "2h 05m")]
)
def test_fmt_minutes(minutes, text):
    assert fmt_minutes(minutes) == text


def test_table_right_aligns_numeric_columns():
    lines = table(["Name", "Min"], [["a", "5.0"], ["bbbb", "25.0"]], right=(1,))
    assert lines == ["Name   Min", "----  ----", "a      5.0", "bbbb  25.0"]
