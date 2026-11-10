"""Session log stored as JSON Lines in a per-user data directory."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

LOG_NAME = "sessions.jsonl"
STATUSES = ("completed", "interrupted")


def data_dir(
    environ: Optional[Mapping[str, str]] = None, platform: Optional[str] = None
) -> Path:
    """Where focusbell keeps its files.

    ``FOCUSBELL_HOME`` wins; otherwise ``%APPDATA%\\focusbell`` on Windows,
    ``$XDG_DATA_HOME/focusbell`` or ``~/.local/share/focusbell`` elsewhere.
    """
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    override = env.get("FOCUSBELL_HOME")
    if override:
        return Path(override)
    if platform.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "focusbell"
        return Path.home() / "AppData" / "Roaming" / "focusbell"
    xdg = env.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "focusbell"
    return Path.home() / ".local" / "share" / "focusbell"


def log_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    return data_dir(environ) / LOG_NAME


@dataclass(frozen=True)
class Session:
    start: datetime  # timezone-aware
    end: datetime  # timezone-aware
    minutes: float
    planned_minutes: Optional[float]
    label: Optional[str]
    status: str
    pauses: int = 0  # times the block was paused; absent in older logs
    paused_minutes: float = 0.0  # wall time spent paused, not counted in ``minutes``
    note: Optional[str] = None  # free text added later with `focusbell note`

    def to_dict(self) -> dict:
        data = {
            "start": self.start.isoformat(timespec="seconds"),
            "end": self.end.isoformat(timespec="seconds"),
            "minutes": self.minutes,
            "planned_minutes": self.planned_minutes,
            "label": self.label,
            "status": self.status,
        }
        if self.pauses:
            data["pauses"] = self.pauses
            data["paused_minutes"] = self.paused_minutes
        if self.note:
            data["note"] = self.note
        return data


def append_record(path: Path, record: dict) -> None:
    """Append one session record as a JSON line, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=False)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if value < 0 or value != value:
        raise ValueError(f"{name} must be non-negative")
    return float(value)


def parse_record(obj: object) -> Session:
    """Validate a decoded JSON object and turn it into a Session."""
    if not isinstance(obj, dict):
        raise ValueError("record is not an object")
    start = _parse_time(obj.get("start"))
    minutes = _number(obj.get("minutes"), "minutes")
    end_raw = obj.get("end")
    end = _parse_time(end_raw) if end_raw is not None else start + timedelta(minutes=minutes)
    planned_raw = obj.get("planned_minutes")
    planned = None if planned_raw is None else _number(planned_raw, "planned_minutes")
    label = obj.get("label")
    if label is not None and not isinstance(label, str):
        raise ValueError("label must be a string")
    status = obj.get("status", "completed")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    pauses_raw = obj.get("pauses", 0)
    if isinstance(pauses_raw, bool) or not isinstance(pauses_raw, int) or pauses_raw < 0:
        raise ValueError("pauses must be a non-negative whole number")
    paused_raw = obj.get("paused_minutes")
    paused = 0.0 if paused_raw is None else _number(paused_raw, "paused_minutes")
    note = obj.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError("note must be a string")
    return Session(start, end, minutes, planned, label or None, status, pauses_raw, paused,
                   note or None)


def set_note(
    path: Path, note: str, select: Optional[Callable[[Session], bool]] = None
) -> Optional[Session]:
    """Store ``note`` on the most recent session, rewriting the log atomically.

    With ``select``, only sessions it accepts are candidates. Every other line
    (corrupt ones included) is kept byte for byte. Returns the updated session,
    or None when the log holds no matching valid session.
    """
    return _update_latest(path, "note", note, select)


def set_label(
    path: Path, label: str, select: Optional[Callable[[Session], bool]] = None
) -> Optional[tuple[Session, Optional[str]]]:
    """Replace the label of the most recent (or selected) session.

    Same atomic, byte-preserving rewrite as :func:`set_note`. Returns the
    updated session and the old label, or None when nothing matched.
    """
    return _update_latest(path, "label", label, select, with_old=True)


def _update_latest(path, key, value, select, with_old=False):
    """Set ``key`` on the newest accepted session; see :func:`set_note`."""
    if not path.exists():
        return None
    lines = path.read_bytes().split(b"\n")
    best: Optional[tuple[datetime, int]] = None
    parsed: dict[int, dict] = {}
    for i, raw in enumerate(lines):
        text = raw.decode("utf-8-sig", errors="replace").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
            session = parse_record(obj)
        except (ValueError, TypeError, OverflowError):
            continue
        if select is not None and not select(session):
            continue
        parsed[i] = obj
        if best is None or session.start >= best[0]:
            best = (session.start, i)
    if best is None:
        return None
    index = best[1]
    obj = parsed[index]
    old = obj.get(key)
    obj[key] = value
    ending = b"\r" if lines[index].endswith(b"\r") else b""
    lines[index] = json.dumps(obj, ensure_ascii=False).encode("utf-8") + ending
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(b"\n".join(lines))
    os.replace(tmp, path)
    updated = parse_record(obj)
    if with_old:
        return updated, (old if isinstance(old, str) and old else None)
    return updated


def read_sessions(
    path: Path, warn: Optional[Callable[[str], None]] = None
) -> list[Session]:
    """Read every valid session; corrupt lines are reported via ``warn`` and skipped."""
    if not path.exists():
        return []
    sessions: list[Session] = []
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                sessions.append(parse_record(json.loads(line)))
            except (ValueError, TypeError, OverflowError) as exc:
                if warn is not None:
                    warn(f"skipping corrupt line {lineno} in {path}: {exc}")
    sessions.sort(key=lambda s: s.start)
    return sessions
