import io
import json
from datetime import datetime, timezone

import pytest

from focusbell.cli import main

START = 1_793_000_000.0  # 2026-10-26T04:53:20Z


class FakeClock:
    """A clock whose ``sleep`` advances time instantly.

    If ``interrupt_at`` is set, the sleep that would cross it stops exactly
    there and raises KeyboardInterrupt, like a Ctrl+C during time.sleep().
    """

    def __init__(self, start=START, interrupt_at=None):
        self.t = float(start)
        self.interrupt_at = interrupt_at
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        if self.interrupt_at is not None and self.t + seconds >= self.interrupt_at:
            self.t = self.interrupt_at
            raise KeyboardInterrupt
        self.t += seconds


class TTY(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real per-user data directory."""
    home = tmp_path / "fbhome"
    monkeypatch.setenv("FOCUSBELL_HOME", str(home))
    monkeypatch.delenv("NO_COLOR", raising=False)
    return home


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def run(isolated_home):
    def _run(*argv, stdout=None, clock=None, now=None, tz=timezone.utc, environ=None):
        out = stdout if stdout is not None else io.StringIO()
        err = io.StringIO()
        clk = clock or FakeClock()
        env = {"FOCUSBELL_HOME": str(isolated_home)} if environ is None else environ
        code = main(
            list(argv),
            stdout=out,
            stderr=err,
            environ=env,
            clock=clk,
            sleep=clk.sleep,
            now=now or (lambda: datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)),
            tz=tz,
        )
        return code, out.getvalue(), err.getvalue()

    return _run


def write_log(home, records, extra_lines=()):
    home.mkdir(parents=True, exist_ok=True)
    path = home / "sessions.jsonl"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
        for line in extra_lines:
            fh.write(line + "\n")
    return path


def rec(start, minutes=25.0, label=None, status="completed", planned=25.0):
    return {
        "start": start,
        "minutes": minutes,
        "planned_minutes": planned,
        "label": label,
        "status": status,
    }
