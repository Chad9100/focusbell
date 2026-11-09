"""Skipping the rest of a break with the s key, driven by a fake clock."""

import io
import json
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from focusbell import timer
from focusbell.cli import main
from focusbell.timer import build_schedule

T0 = 1_793_000_000.0  # 2026-10-26T04:53:20Z


class Clock:
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

    def __call__(self):
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


def test_s_ends_a_short_break_and_the_next_block_starts_at_once():
    clock = Clock()
    # Work 0-10, short break from 10 skipped at 12, work 12-22, long break 22-27.
    result, out = run(build_schedule(10, 60, 5, cycles=2), clock, [(12, "s")])
    assert clock() - T0 == pytest.approx(27)
    assert result.skipped == 1
    assert result.completed == 2
    assert result.focus_seconds == 20
    assert [r["start"] for r in result.records] == [iso(0), iso(12)]
    assert "Short break skipped. Back to work." in out.splitlines()
    assert "Short break over. Back to work." not in out


def test_s_during_work_is_ignored():
    clock = Clock()
    result, out = run(build_schedule(10, 5, 5, cycles=1), clock, [(3, "s")])
    assert result.skipped == 0
    assert result.completed == 1
    assert result.records[0]["minutes"] == round(10 / 60, 2)
    assert clock() - T0 == pytest.approx(15)
    assert "skipped" not in out


def test_skipping_the_final_long_break_finishes_the_session():
    clock = Clock()
    result, out = run(build_schedule(10, 5, 300, cycles=1), clock, [(11, "s")])
    assert clock() - T0 == pytest.approx(11)
    assert result.skipped == 1
    assert out.splitlines()[-1] == "Long break skipped. All done. Nice work."


def test_skipping_a_paused_break_ends_the_pause_too():
    clock = Clock()
    # Short break starts at 10, paused at 11, skipped at 41 while still paused.
    result, _ = run(build_schedule(10, 60, 5, cycles=2), clock,
                    [(11, "p"), (41, "s")])
    assert result.skipped == 1
    assert result.pauses == 1
    assert result.paused_seconds == pytest.approx(30)
    assert result.records[1]["start"] == iso(41)
    assert "pauses" not in result.records[1]  # the break's pause is not the block's


def test_a_skipped_break_rings_no_bell_and_sends_no_notification():
    clock = Clock()
    sent = []
    _, out = run(build_schedule(10, 60, 5, cycles=2), clock, [(12, "s")], bell=True,
                 notify=lambda title, message: sent.append(message))
    assert out.count("\a") == 3  # two work blocks and the long break, not the skip
    assert "Short break skipped. Back to work." not in sent
    assert sent == ["Work block 1 done. Short break next.",
                    "Work block 2 done. Long break next.",
                    "All done. Nice work."]


def test_tty_line_shows_time_left_when_skipped():
    clock = Clock()
    _, out = run(build_schedule(10, 60, 5, cycles=2), clock, [(12, "s")],
                 out=TTY(), tty=True)
    lines = out.split("\n")
    assert lines[2].endswith("Short break  00:58  skipped")
    assert "Short break  00:00" not in out


def test_ctrl_c_after_a_skip_still_logs_the_partial_block():
    clock = Clock(interrupt_at=T0 + 20)
    result, _ = run(build_schedule(10, 60, 5, cycles=2), clock, [(12, "s")])
    assert result.interrupted and result.skipped == 1
    assert [r["status"] for r in result.records] == ["completed", "interrupted"]
    assert result.records[1]["minutes"] == round(8 / 60, 2)


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


START = ["start", "--seconds", "--work", "5", "--short", "30", "--long", "30",
         "--cycles", "2", "--no-bell"]


def test_cli_banner_and_summary_mention_skips(tmp_path):
    clock = Clock()
    # Work 0-5, short break skipped at 7, work 7-12, long break skipped at 13.
    code, out, err = cli(START, tmp_path, clock, [(7, "s"), (13, "s")])
    assert code == 0, err
    assert "p to pause, s to skip a break, Ctrl+C to stop." in out
    assert out.splitlines()[-1] == \
        "Focused 10s: 2 of 2 work block(s) completed. Skipped 2 break(s)."
    lines = (tmp_path / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["start"] for r in records] == [iso(0), iso(7)]
    # The log format is unchanged: skipping adds no fields.
    assert set(records[0]) == {"start", "end", "minutes", "planned_minutes", "label",
                               "status"}


def test_cli_summary_without_skips_is_unchanged(tmp_path):
    clock = Clock()
    code, out, _ = cli(START, tmp_path, clock, [])
    assert code == 0
    assert out.splitlines()[-1] == "Focused 10s: 2 of 2 work block(s) completed."
