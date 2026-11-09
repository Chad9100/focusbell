"""Pause and resume with the p key, driven by a fake clock and scripted keys."""

import io
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from focusbell import keys, timer
from focusbell.cli import main
from focusbell.log import parse_record, read_sessions
from focusbell.timer import build_schedule

T0 = 1_793_000_000.0  # 2026-10-26T04:53:20Z


class Clock:
    """Fake clock whose sleep advances instantly; can raise Ctrl+C at a time."""

    def __init__(self, start=T0, interrupt_at=None):
        self.t = start
        self.interrupt_at = interrupt_at
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.interrupt_at is not None and self.t + seconds >= self.interrupt_at:
            self.t = self.interrupt_at
            raise KeyboardInterrupt
        self.t += seconds


class Keys:
    """Delivers each scripted key once the clock reaches its time (offset from T0)."""

    def __init__(self, clock, presses):
        self.clock = clock
        self.pending = sorted((T0 + at, key) for at, key in presses)
        self.polls = 0

    def __call__(self):
        self.polls += 1
        if self.pending and self.clock() >= self.pending[0][0]:
            return self.pending.pop(0)[1]
        return None


class TTY(io.StringIO):
    def isatty(self):
        return True


def iso(offset):
    return datetime.fromtimestamp(T0 + offset, timezone.utc).isoformat(timespec="seconds")


def run(schedule, clock, presses, **kw):
    out = kw.pop("out", None) or io.StringIO()
    kw.setdefault("tty", False)
    kw.setdefault("bell", False)
    result = timer.run(schedule, clock=clock, sleep=clock.sleep, out=out,
                       keys=Keys(clock, presses), **kw)
    return result, out.getvalue()


# ------------------------------------------------------------ timer loop


def test_pause_pushes_the_phase_end_back_and_is_not_focus_time():
    clock = Clock()
    # Pause 10 s into a 60 s block, resume 30 s later.
    result, _ = run(build_schedule(60, 5, 5, cycles=1), clock, [(10, "p"), (40, "p")])
    assert clock() - T0 == pytest.approx(60 + 30 + 5)
    assert result.completed == 1
    assert result.focus_seconds == 60
    assert result.pauses == 1
    assert result.paused_seconds == pytest.approx(30)
    (record,) = result.records
    assert record["minutes"] == 1.0
    assert record["pauses"] == 1
    assert record["paused_minutes"] == 0.5
    assert record["start"] == iso(0)
    assert record["end"] == iso(90)  # wall clock end includes the pause


def test_several_pauses_are_counted_and_summed():
    clock = Clock()
    presses = [(5, "p"), (15, "p"), (20, "p"), (50, "p")]
    result, _ = run(build_schedule(60, 5, 5, cycles=1), clock, presses)
    (record,) = result.records
    assert record["pauses"] == 2
    assert record["paused_minutes"] == pytest.approx((10 + 30) / 60, abs=0.01)
    assert record["minutes"] == 1.0


def test_unpaused_records_have_no_pause_fields():
    clock = Clock()
    result, _ = run(build_schedule(60, 5, 5, cycles=1), clock, [])
    assert set(result.records[0]) == {
        "start", "end", "minutes", "planned_minutes", "label", "status"
    }


def test_other_keys_are_ignored():
    clock = Clock()
    result, _ = run(build_schedule(10, 5, 5, cycles=1), clock, [(2, "x"), (3, "q")])
    assert result.pauses == 0
    assert clock() - T0 == pytest.approx(15)


def test_pausing_a_break_extends_it_but_logs_no_record():
    clock = Clock()
    # Work 0-10, short break 10-15 paused 12..20, work 23-33, long break.
    result, _ = run(build_schedule(10, 5, 5, cycles=2), clock, [(12, "p"), (20, "p")])
    assert result.pauses == 1
    assert [r.get("pauses") for r in result.records] == [None, None]
    assert result.records[1]["start"] == iso(23)


def test_ctrl_c_while_paused_logs_only_the_time_worked():
    # 20 s of work, pause, then Ctrl+C 100 s into the pause.
    clock = Clock(interrupt_at=T0 + 120)
    result, _ = run(build_schedule(1500, 300, 900, cycles=4), clock, [(20, "p")])
    assert result.interrupted
    (record,) = result.records
    assert record["status"] == "interrupted"
    assert record["minutes"] == pytest.approx(20 / 60, abs=0.01)
    assert record["pauses"] == 1
    assert record["paused_minutes"] == pytest.approx(100 / 60, abs=0.01)
    assert record["end"] == iso(120)
    assert result.paused_seconds == pytest.approx(100)


def test_ctrl_c_after_resume_excludes_the_finished_pause():
    clock = Clock(interrupt_at=T0 + 200)
    result, _ = run(build_schedule(1500, 300, 900, cycles=4), clock, [(30, "p"), (90, "p")])
    (record,) = result.records
    assert record["minutes"] == pytest.approx(140 / 60, abs=0.01)
    assert record["paused_minutes"] == 1.0


def test_non_tty_prints_paused_and_resumed_lines():
    clock = Clock()
    _, out = run(build_schedule(60, 5, 5, cycles=1), clock, [(10, "p"), (40, "p")],
                 label="thesis")
    lines = out.splitlines()
    assert "Work 1/1: paused at 00:50 left  [thesis]. Press p to resume." in lines
    assert "Work 1/1: resumed, 00:50 left  [thesis]" in lines


def test_tty_shows_frozen_countdown_while_paused():
    clock = Clock()
    _, out = run(build_schedule(60, 5, 5, cycles=1), clock, [(10, "p"), (40, "p")],
                 out=TTY(), tty=True)
    first = out.split("\n")[0]
    assert first.count("00:50  paused, p to resume") >= 25  # redrawn every tick
    assert "00:49" in first.split("paused")[-1]  # counting again after resume


def test_keys_polled_every_tick():
    clock = Clock()
    k = Keys(clock, [])
    timer.run(build_schedule(5, 1, 1, cycles=1), clock=clock, sleep=clock.sleep,
              out=io.StringIO(), tty=False, keys=k)
    assert k.polls == len(clock.sleeps) + 2  # plus one final poll per phase


# ------------------------------------------------------------ log format


def test_old_records_without_pause_fields_still_parse():
    s = parse_record({"start": "2026-11-09T09:00:00+00:00", "minutes": 25})
    assert s.pauses == 0 and s.paused_minutes == 0.0
    assert "pauses" not in s.to_dict()


def test_pause_fields_round_trip():
    raw = {"start": "2026-11-09T09:00:00+00:00", "end": "2026-11-09T09:30:00+00:00",
           "minutes": 25.0, "planned_minutes": 25.0, "label": None,
           "status": "completed", "pauses": 2, "paused_minutes": 5.0}
    assert parse_record(raw).to_dict() == raw


@pytest.mark.parametrize("bad", [{"pauses": -1}, {"pauses": 1.5}, {"pauses": True},
                                 {"pauses": 1, "paused_minutes": "x"}])
def test_invalid_pause_fields_rejected(bad):
    with pytest.raises(ValueError):
        parse_record({"start": "2026-11-09T09:00:00+00:00", "minutes": 25, **bad})


# ------------------------------------------------------------ CLI


def cli(argv, home, clock, presses=None):
    out, err = io.StringIO(), io.StringIO()

    @contextmanager
    def reader():
        yield None if presses is None else Keys(clock, presses)

    code = main(argv, stdout=out, stderr=err, environ={"FOCUSBELL_HOME": str(home)},
                clock=clock, sleep=clock.sleep, tz=timezone.utc,
                now=lambda: datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc),
                key_reader=reader)
    return code, out.getvalue(), err.getvalue()


START = ["start", "--seconds", "--work", "20", "--short", "2", "--long", "2",
         "--cycles", "1", "--no-bell"]


def test_cli_pause_is_logged_and_summarised(tmp_path):
    clock = Clock()
    code, out, err = cli(START, tmp_path, clock, [(5, "p"), (12, "p")])
    assert code == 0, err
    assert "p to pause, s to skip a break, Ctrl+C to stop." in out
    assert "Focused 20s: 1 of 1 work block(s) completed. Paused 1 time(s), 7s in total." in out
    lines = (tmp_path / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["pauses"] == 1 and record["paused_minutes"] == 0.12
    assert record["minutes"] == 0.33


def test_cli_polls_keys_four_times_a_second(tmp_path):
    clock = Clock()
    cli(START, tmp_path, clock, [])
    assert set(clock.sleeps) == {0.25}


def test_cli_without_a_key_reader_keeps_old_banner_and_ticks(tmp_path):
    clock = Clock()
    code, out, _ = cli(START, tmp_path, clock, None)
    assert code == 0
    assert "Ctrl+C to stop." in out and "p to pause" not in out
    assert "Paused" not in out
    assert set(clock.sleeps) == {1.0}


def test_cli_interrupted_while_paused(tmp_path):
    clock = Clock(interrupt_at=T0 + 30)
    code, out, _ = cli(START, tmp_path, clock, [(8, "p")])
    assert code == 130
    assert "Focused 8s: 0 of 1 work block(s) completed, 1 interrupted." \
           " Paused 1 time(s), 22s in total. Stopped." in out
    (s,) = read_sessions(tmp_path / "sessions.jsonl")
    assert s.status == "interrupted" and s.pauses == 1


def test_log_command_reports_pauses(tmp_path):
    clock = Clock()
    cli(START, tmp_path, clock, [(5, "p"), (65, "p")])
    code, out, _ = cli(["log"], tmp_path, clock)
    assert code == 0
    assert "1 session(s), 0m focused. 1 pause(s) in 1 session(s), 1m on hold (not counted)." in out


# ------------------------------------------------------------ key reader


def test_key_reader_yields_none_when_stdin_is_not_a_terminal():
    with keys.key_reader(io.StringIO("p")) as poll:
        assert poll is None


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt is Windows only")
def test_windows_poll_skips_extended_key_prefixes(monkeypatch):
    import msvcrt

    queue = ["\xe0", "H", "P"]
    monkeypatch.setattr(msvcrt, "kbhit", lambda: bool(queue))
    monkeypatch.setattr(msvcrt, "getwch", lambda: queue.pop(0))
    with keys.key_reader(TTY()) as poll:
        assert poll() == "p"
        assert poll() is None


@pytest.mark.skipif(sys.platform == "win32", reason="termios is POSIX only")
def test_posix_reader_restores_terminal_settings():
    pty = pytest.importorskip("pty")
    import os
    import termios

    master, slave = pty.openpty()
    try:
        stream = os.fdopen(slave, "r", closefd=False)
        before = termios.tcgetattr(slave)
        with keys.key_reader(stream) as poll:
            assert poll is not None
            assert poll() is None
            os.write(master, b"P")
            got = None
            for _ in range(200):  # the pty may take a moment to deliver the byte
                got = poll()
                if got is not None:
                    break
                time.sleep(0.01)
            assert got == "p"
            assert termios.tcgetattr(slave)[3] & termios.ICANON == 0
        assert termios.tcgetattr(slave) == before
    finally:
        os.close(master)
        os.close(slave)
