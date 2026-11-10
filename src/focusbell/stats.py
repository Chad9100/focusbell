"""Aggregate logged sessions into per-day focus minutes, rates and streaks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Iterable, Optional

from .log import Session


def to_local(dt: datetime, tz: Optional[tzinfo] = None) -> datetime:
    """Convert an aware datetime to ``tz`` (or the system local zone)."""
    return dt.astimezone(tz) if tz is not None else dt.astimezone()


def minutes_by_day(
    sessions: Iterable[Session], tz: Optional[tzinfo] = None
) -> dict[date, float]:
    """Focus minutes per local calendar day.

    A session that runs past local midnight is split between the two days.
    """
    totals: dict[date, float] = defaultdict(float)
    for s in sessions:
        cur = to_local(s.start, tz)
        stop = to_local(s.start + timedelta(minutes=s.minutes), tz)
        while cur < stop:
            midnight = datetime.combine(
                cur.date() + timedelta(days=1), time.min, tzinfo=cur.tzinfo
            )
            seg_end = min(midnight, stop)
            totals[cur.date()] += (seg_end - cur).total_seconds() / 60
            cur = to_local(seg_end, tz)
    return dict(totals)


def current_streak(active_days: Iterable[date], today: date) -> int:
    """Consecutive active days ending today (or yesterday, if today is still empty)."""
    days = set(active_days)
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


@dataclass
class Stats:
    first_day: date
    last_day: date
    per_day: list[tuple[date, float]]
    total_minutes: float
    sessions: int
    completed: int
    interrupted: int
    top_labels: list[tuple[str, float]]
    streak: int

    @property
    def completion_rate(self) -> Optional[float]:
        if self.sessions == 0:
            return None
        return self.completed / self.sessions

    @property
    def days(self) -> int:
        return len(self.per_day)


def compute_stats(
    sessions: list[Session],
    days: int,
    today: date,
    tz: Optional[tzinfo] = None,
    top: int = 3,
) -> Stats:
    if days < 1:
        raise ValueError("days must be at least 1")
    first = today - timedelta(days=days - 1)
    by_day = minutes_by_day(sessions, tz)
    per_day = [
        (first + timedelta(days=i), by_day.get(first + timedelta(days=i), 0.0))
        for i in range(days)
    ]
    in_window = [s for s in sessions if first <= to_local(s.start, tz).date() <= today]
    completed = sum(1 for s in in_window if s.status == "completed")
    labels: dict[str, float] = defaultdict(float)
    for s in in_window:
        if s.label:
            labels[s.label] += s.minutes
    top_labels = sorted(labels.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    active = [d for d, m in by_day.items() if m > 0]
    return Stats(
        first_day=first,
        last_day=today,
        per_day=per_day,
        total_minutes=sum(m for _, m in per_day),
        sessions=len(in_window),
        completed=completed,
        interrupted=len(in_window) - completed,
        top_labels=top_labels,
        streak=current_streak(active, today),
    )


@dataclass
class TaskStat:
    label: Optional[str]  # None groups the sessions logged without a label
    sessions: int
    completed: int
    minutes: float
    last_day: date


def by_label(
    sessions: Iterable[Session],
    first: date,
    last: date,
    tz: Optional[tzinfo] = None,
) -> list[TaskStat]:
    """Sessions that started between ``first`` and ``last`` (local days), per label.

    Sorted by focus minutes (most first), then label; the unlabelled group,
    if any, always comes last.
    """
    groups: dict[Optional[str], TaskStat] = {}
    for s in sessions:
        day = to_local(s.start, tz).date()
        if not first <= day <= last:
            continue
        st = groups.get(s.label)
        if st is None:
            st = groups[s.label] = TaskStat(s.label, 0, 0, 0.0, day)
        st.sessions += 1
        st.completed += s.status == "completed"
        st.minutes += s.minutes
        st.last_day = max(st.last_day, day)
    return sorted(
        groups.values(),
        key=lambda t: (t.label is None, -t.minutes, t.label or ""),
    )
