"""Schedule generation and the countdown loop.

The loop never calls ``time`` directly: it receives a ``clock`` (returns epoch
seconds) and a ``sleep`` function, so tests can drive it with a fake clock and
finish instantly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, TextIO

WORK = "work"
SHORT = "short"
LONG = "long"

PHASE_NAMES = {WORK: "Work", SHORT: "Short break", LONG: "Long break"}

COMPLETED = "completed"
INTERRUPTED = "interrupted"

# Interrupted work blocks shorter than this are not worth logging.
MIN_RECORD_SECONDS = 1.0


@dataclass(frozen=True)
class Phase:
    kind: str
    seconds: float
    number: int  # work block number (1-based); for a break, the block it follows
    total: int  # total work blocks in the schedule

    @property
    def name(self) -> str:
        return PHASE_NAMES[self.kind]


def build_schedule(
    work: float, short: float, long: float, cycles: int, sets: int = 1
) -> list[Phase]:
    """Return the phases for ``sets`` rounds of ``cycles`` work blocks.

    Work blocks are separated by short breaks; every ``cycles``-th work block is
    followed by a long break instead. All durations are in seconds.
    """
    if work <= 0 or short <= 0 or long <= 0:
        raise ValueError("durations must be positive")
    if cycles < 1 or sets < 1:
        raise ValueError("cycles and sets must be at least 1")
    total = cycles * sets
    phases: list[Phase] = []
    number = 0
    for _ in range(sets):
        for i in range(1, cycles + 1):
            number += 1
            phases.append(Phase(WORK, float(work), number, total))
            if i < cycles:
                phases.append(Phase(SHORT, float(short), number, total))
            else:
                phases.append(Phase(LONG, float(long), number, total))
    return phases


def format_clock(seconds: float) -> str:
    """Format remaining seconds as ``MM:SS`` (or ``H:MM:SS`` past an hour).

    Partial seconds round up, so a countdown shows 00:01 until it is really over.
    """
    whole = max(0, math.ceil(seconds - 1e-9))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def make_record(
    start: float, elapsed: float, planned: float, label: Optional[str], status: str
) -> dict:
    return {
        "start": _iso(start),
        "end": _iso(start + elapsed),
        "minutes": round(elapsed / 60, 2),
        "planned_minutes": round(planned / 60, 2),
        "label": label,
        "status": status,
    }


@dataclass
class RunResult:
    completed: int = 0
    interrupted: bool = False
    focus_seconds: float = 0.0
    records: list[dict] = field(default_factory=list)


def _phase_title(phase: Phase) -> str:
    if phase.kind == WORK:
        return f"Work {phase.number}/{phase.total}"
    return phase.name


def run(
    schedule: list[Phase],
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    out: TextIO,
    label: Optional[str] = None,
    bell: bool = True,
    tty: bool = True,
    on_record: Optional[Callable[[dict], None]] = None,
    tick: float = 1.0,
    report_every: float = 60.0,
    paint: Optional[Callable[[str, str], str]] = None,
) -> RunResult:
    """Run every phase of ``schedule``; return what happened.

    On a TTY the countdown is a single line rewritten with ``\\r``. Otherwise a
    plain line is printed when a phase starts and every ``report_every``
    seconds. Ctrl+C (KeyboardInterrupt) stops the run; a work block in progress
    is recorded as interrupted with the minutes actually worked.
    """
    paint = paint or (lambda _style, text: text)
    result = RunResult()
    suffix = f"  [{label}]" if label else ""
    width = 0

    def emit(record: dict) -> None:
        result.records.append(record)
        if on_record is not None:
            on_record(record)

    def draw(text: str) -> None:
        nonlocal width
        pad = " " * max(0, width - len(text))
        width = len(text)
        out.write("\r" + text + pad)
        out.flush()

    phase: Optional[Phase] = None
    start = 0.0
    try:
        for idx, phase in enumerate(schedule):
            start = clock()
            end = start + phase.seconds
            style = "work" if phase.kind == WORK else "break"
            title = _phase_title(phase)
            last_bucket = None
            width = 0
            while True:
                remaining = end - clock()
                if remaining <= 0:
                    break
                if tty:
                    draw(f"{paint(style, title)}  {format_clock(remaining)}{suffix}")
                else:
                    bucket = math.ceil(remaining / report_every)
                    if bucket != last_bucket:
                        last_bucket = bucket
                        out.write(f"{title}: {format_clock(remaining)} left{suffix}\n")
                        out.flush()
                sleep(min(tick, remaining))
            if tty:
                draw(f"{paint(style, title)}  {format_clock(0)}{suffix}")
                out.write("\n")
            if phase.kind == WORK:
                result.completed += 1
                result.focus_seconds += phase.seconds
                emit(make_record(start, phase.seconds, phase.seconds, label, COMPLETED))
            if bell:
                out.write("\a")
            nxt = schedule[idx + 1] if idx + 1 < len(schedule) else None
            out.write(paint("note", _transition_message(phase, nxt)) + "\n")
            out.flush()
            phase = None
    except KeyboardInterrupt:
        result.interrupted = True
        if tty:
            out.write("\n")
        if phase is not None and phase.kind == WORK:
            elapsed = max(0.0, min(clock() - start, phase.seconds))
            if elapsed >= MIN_RECORD_SECONDS:
                result.focus_seconds += elapsed
                emit(make_record(start, elapsed, phase.seconds, label, INTERRUPTED))
        out.flush()
    return result


def _transition_message(phase: Phase, nxt: Optional[Phase]) -> str:
    if nxt is None:
        return "All done. Nice work."
    if phase.kind == WORK:
        return f"Work block {phase.number} done. {nxt.name} next."
    return f"{phase.name} over. Back to work."
