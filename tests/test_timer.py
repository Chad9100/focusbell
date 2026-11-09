import io
from datetime import datetime, timezone

import pytest

from conftest import TTY, FakeClock
from focusbell import timer
from focusbell.timer import LONG, SHORT, WORK, build_schedule, format_clock


def kinds(schedule):
    return [p.kind for p in schedule]


# ------------------------------------------------------------ schedule


def test_default_schedule_has_long_break_after_fourth_block():
    s = build_schedule(25 * 60, 5 * 60, 15 * 60, 4)
    assert kinds(s) == [WORK, SHORT, WORK, SHORT, WORK, SHORT, WORK, LONG]


def test_long_break_after_every_n_blocks_across_sets():
    s = build_schedule(10, 2, 5, cycles=3, sets=2)
    assert kinds(s) == [WORK, SHORT, WORK, SHORT, WORK, LONG] * 2
    longs = [p.number for p in s if p.kind == LONG]
    assert longs == [3, 6]


def test_single_cycle_is_work_then_long_break():
    assert kinds(build_schedule(10, 2, 5, cycles=1)) == [WORK, LONG]


def test_work_blocks_are_numbered_with_total():
    s = build_schedule(10, 2, 5, cycles=2, sets=2)
    work = [(p.number, p.total) for p in s if p.kind == WORK]
    assert work == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_schedule_keeps_durations_in_seconds():
    s = build_schedule(1500, 300, 900, cycles=2)
    assert [p.seconds for p in s] == [1500, 300, 1500, 900]


@pytest.mark.parametrize("args", [(0, 5, 15, 4), (25, -1, 15, 4), (25, 5, 0, 4)])
def test_non_positive_durations_rejected(args):
    with pytest.raises(ValueError):
        build_schedule(*args)


@pytest.mark.parametrize("cycles,sets", [(0, 1), (4, 0)])
def test_cycles_and_sets_must_be_positive(cycles, sets):
    with pytest.raises(ValueError):
        build_schedule(25, 5, 15, cycles, sets)


# ------------------------------------------------------------ formatting


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "00:00"),
        (-3, "00:00"),
        (0.4, "00:01"),
        (59.2, "01:00"),
        (60, "01:00"),
        (61, "01:01"),
        (1500, "25:00"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3725, "1:02:05"),
    ],
)
def test_format_clock(seconds, expected):
    assert format_clock(seconds) == expected


# ------------------------------------------------------------ the loop


def run(schedule, clock, **kw):
    out = kw.pop("out", None) or io.StringIO()
    kw.setdefault("tty", False)
    result = timer.run(schedule, clock=clock, sleep=clock.sleep, out=out, **kw)
    return result, out.getvalue()


def test_full_run_takes_exactly_the_scheduled_time(clock):
    s = build_schedule(60, 10, 30, cycles=2)
    start = clock()
    result, _ = run(s, clock)
    assert clock() - start == pytest.approx(60 + 10 + 60 + 30)
    assert result.completed == 2
    assert not result.interrupted
    assert result.focus_seconds == 120


def test_full_run_records_completed_blocks_with_timestamps(clock):
    s = build_schedule(1500, 300, 900, cycles=2)
    t0 = clock()
    result, _ = run(s, clock)
    assert [r["status"] for r in result.records] == ["completed", "completed"]
    first, second = result.records
    assert first["start"] == datetime.fromtimestamp(t0, timezone.utc).isoformat(timespec="seconds")
    assert first["minutes"] == 25.0 and first["planned_minutes"] == 25.0
    expected_second = datetime.fromtimestamp(t0 + 1800, timezone.utc)
    assert second["start"] == expected_second.isoformat(timespec="seconds")
    assert second["end"] == datetime.fromtimestamp(t0 + 3300, timezone.utc).isoformat(timespec="seconds")


def test_on_record_called_once_per_work_block(clock):
    seen = []
    run(build_schedule(5, 1, 2, cycles=3), clock, on_record=seen.append)
    assert len(seen) == 3


def test_bell_rings_at_every_transition(clock):
    s = build_schedule(3, 1, 2, cycles=2)
    _, out = run(s, clock, bell=True)
    assert out.count("\a") == len(s)


def test_no_bell_when_disabled(clock):
    _, out = run(build_schedule(3, 1, 2, cycles=2), clock, bell=False)
    assert "\a" not in out


def test_tty_countdown_rewrites_one_line(clock):
    out = TTY()
    _, text = run(build_schedule(3, 1, 1, cycles=1), clock, out=out, tty=True, bell=False)
    first_phase = text.split("\n")[0]
    assert first_phase.count("\r") >= 4
    for stamp in ("00:03", "00:02", "00:01", "00:00"):
        assert stamp in first_phase
    assert "Work 1/1" in first_phase


def test_tty_ticks_once_per_second(clock):
    run(build_schedule(5, 2, 2, cycles=1), clock, tty=True, out=TTY())
    assert clock.sleeps == [1.0] * 7


def test_non_tty_prints_plain_periodic_lines(clock):
    s = build_schedule(150, 60, 60, cycles=1)
    _, out = run(s, clock, report_every=60, bell=False)
    assert "\r" not in out
    lines = out.splitlines()
    assert lines[:3] == ["Work 1/1: 02:30 left", "Work 1/1: 02:00 left", "Work 1/1: 01:00 left"]
    assert "Long break: 01:00 left" in lines


def test_non_tty_reports_once_per_interval(clock):
    _, out = run(build_schedule(25 * 60, 60, 60, cycles=1), clock, report_every=60, bell=False)
    assert sum(1 for line in out.splitlines() if line.startswith("Work 1/1:")) == 25


def test_ctrl_c_mid_work_records_interrupted_minutes():
    clock = FakeClock()
    clock.interrupt_at = clock() + 10 * 60  # Ctrl+C 10 minutes into the first block
    result, _ = run(build_schedule(1500, 300, 900, cycles=4), clock)
    assert result.interrupted
    assert result.completed == 0
    (record,) = result.records
    assert record["status"] == "interrupted"
    assert record["minutes"] == 10.0
    assert record["planned_minutes"] == 25.0


def test_ctrl_c_in_second_block_keeps_first_completed():
    clock = FakeClock()
    clock.interrupt_at = clock() + 1500 + 300 + 7.5 * 60
    result, _ = run(build_schedule(1500, 300, 900, cycles=4), clock)
    assert [r["status"] for r in result.records] == ["completed", "interrupted"]
    assert result.records[1]["minutes"] == 7.5
    assert result.focus_seconds == 1500 + 450


def test_ctrl_c_during_break_records_nothing_extra():
    clock = FakeClock()
    clock.interrupt_at = clock() + 1500 + 120
    result, _ = run(build_schedule(1500, 300, 900, cycles=4), clock)
    assert result.interrupted
    assert [r["status"] for r in result.records] == ["completed"]


def test_ctrl_c_immediately_records_nothing():
    clock = FakeClock()
    clock.interrupt_at = clock() + 0.5
    result, _ = run(build_schedule(1500, 300, 900, cycles=4), clock)
    assert result.interrupted and result.records == []


def test_ctrl_c_on_tty_ends_the_countdown_line():
    clock = FakeClock()
    clock.interrupt_at = clock() + 2
    out = TTY()
    run(build_schedule(10, 5, 5, cycles=1), clock, out=out, tty=True)
    assert out.getvalue().endswith("\n")


def test_label_shown_and_recorded(clock):
    result, out = run(build_schedule(2, 1, 1, cycles=1), clock, label="thesis")
    assert "[thesis]" in out
    assert result.records[0]["label"] == "thesis"


def test_transition_messages(clock):
    _, out = run(build_schedule(2, 1, 1, cycles=2), clock, bell=False)
    assert "Work block 1 done. Short break next." in out
    assert "Short break over. Back to work." in out
    assert "Work block 2 done. Long break next." in out
    assert out.rstrip().endswith("All done. Nice work.")


def test_paint_hook_is_applied(clock):
    calls = []

    def paint(style, text):
        calls.append(style)
        return f"<{style}>{text}"

    _, out = run(build_schedule(2, 1, 1, cycles=1), clock, out=TTY(), tty=True, paint=paint)
    assert "<work>Work 1/1" in out
    assert "break" in calls and "note" in calls
