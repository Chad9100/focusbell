"""iCalendar (RFC 5545) export: one VEVENT per session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .log import Session

CRLF = "\r\n"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold to at most 75 octets per line, never splitting a UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    current = ""
    limit = 75
    for ch in line:
        if len((current + ch).encode("utf-8")) > limit:
            parts.append(current)
            current = ch
            limit = 74  # continuation lines start with a space
        else:
            current += ch
    parts.append(current)
    return (CRLF + " ").join(parts)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _minutes(value: float) -> str:
    return f"{value:g}"


def _description(s: Session) -> str:
    text = f"{s.status.capitalize()}: {_minutes(s.minutes)} min focused"
    if s.planned_minutes is not None:
        text += f" of {_minutes(s.planned_minutes)} planned"
    if s.pauses:
        text += f"; paused {s.pauses}x ({_minutes(s.paused_minutes)} min)"
    return text


def to_ics(sessions: Iterable[Session]) -> str:
    """Render sessions as a VCALENDAR; times are UTC, lines CRLF-terminated."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//focusbell//focus sessions//EN",
        "CALSCALE:GREGORIAN",
    ]
    seen: dict[str, int] = {}
    for s in sessions:
        stamp = _utc(s.start)
        n = seen.get(stamp, 0)
        seen[stamp] = n + 1
        uid = f"{stamp}{'' if n == 0 else '-' + str(n)}@focusbell"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_utc(s.end)}",
            f"DTSTART:{stamp}",
            f"DTEND:{_utc(s.end)}",
            "SUMMARY:" + _escape(f"Focus: {s.label}" if s.label else "Focus"),
            "DESCRIPTION:" + _escape(_description(s)),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return CRLF.join(_fold(x) for x in lines) + CRLF
