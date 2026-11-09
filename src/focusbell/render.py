"""Terminal output helpers: color decisions, bar charts and tables."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence, TextIO

_CODES = {
    "work": "1;31",
    "break": "1;32",
    "note": "2",
    "bar": "36",
    "head": "1",
    "warn": "33",
    "ok": "32",
}

BLOCK_FULL = "█"
BLOCK_EMPTY = "░"


def isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def use_color(mode: str, stream: TextIO, environ: Mapping[str, str]) -> bool:
    """``always``/``never`` are absolute; ``auto`` means a TTY with NO_COLOR unset."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    return "NO_COLOR" not in environ and isatty(stream)


def can_encode(stream: TextIO, text: str) -> bool:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


class Painter:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, style: str, text: str) -> str:
        if not self.enabled or style not in _CODES:
            return text
        return f"\x1b[{_CODES[style]}m{text}\x1b[0m"


def fmt_minutes(minutes: float) -> str:
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours:
        return f"{hours}h {mins:02d}m"
    return f"{mins}m"


def bar(value: float, maximum: float, width: int, unicode: bool = True) -> str:
    full, empty = (BLOCK_FULL, BLOCK_EMPTY) if unicode else ("#", ".")
    if maximum <= 0:
        filled = 0
    else:
        filled = int(round(width * min(value, maximum) / maximum))
        if value > 0 and filled == 0:
            filled = 1
    return full * filled + empty * (width - filled)


def bar_chart(
    rows: Sequence[tuple[str, float]],
    width: int = 30,
    unicode: bool = True,
    paint: Optional[Painter] = None,
) -> list[str]:
    paint = paint or Painter(False)
    maximum = max((v for _, v in rows), default=0.0)
    label_w = max((len(lbl) for lbl, _ in rows), default=0)
    lines = []
    for lbl, value in rows:
        b = paint("bar", bar(value, maximum, width, unicode))
        lines.append(f"{lbl.ljust(label_w)}  {b}  {fmt_minutes(value):>7}")
    return lines


def table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], right: Sequence[int] = ()
) -> list[str]:
    """Plain aligned text table; columns listed in ``right`` are right-aligned."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row: Sequence[str]) -> str:
        cells = [
            cell.rjust(widths[i]) if i in right else cell.ljust(widths[i])
            for i, cell in enumerate(row)
        ]
        return "  ".join(cells).rstrip()

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(r) for r in rows)
    return lines
