import json
from datetime import date, datetime, timedelta, timezone

import pytest

from focusbell.config import ConfigError, validate
from focusbell.log import parse_record
from focusbell.stats import goal_progress, week_start

UTC = timezone.utc
MONDAY = date(2026, 11, 9)
WEDNESDAY = date(2026, 11, 11)
SUNDAY = date(2026, 11, 15)


def record(start, minutes=25.0, status="completed"):
    return {"start": start, "minutes": minutes, "planned_minutes": 25.0,
            "label": None, "status": status}


def sessions(*records):
    return [parse_record(r) for r in records]


def write_log(home, records):
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "sessions.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# ------------------------------------------------------------ config


@pytest.mark.parametrize("value,expected", [("600", 600), ("0", 0), (10080, 10080)])
def test_weekly_goal_accepts_whole_minutes(value, expected):
    assert validate("weekly_goal", value) == expected


@pytest.mark.parametrize("value", ["-1", "10081", "90.5", "lots", True])
def test_weekly_goal_rejects_bad_values(value):
    with pytest.raises(ConfigError):
        validate("weekly_goal", value)


# ------------------------------------------------------------ progress


def test_week_starts_on_monday():
    assert week_start(MONDAY) == MONDAY
    assert week_start(WEDNESDAY) == MONDAY
    assert week_start(SUNDAY) == MONDAY
    assert week_start(MONDAY - timedelta(days=1)) == date(2026, 11, 2)


def test_progress_counts_only_this_week_up_to_today():
    s = sessions(
        record("2026-11-08T10:00:00+00:00", 50),  # last Sunday
        record("2026-11-09T10:00:00+00:00", 25),
        record("2026-11-10T10:00:00+00:00", 12, "interrupted"),
        record("2026-11-11T10:00:00+00:00", 25),
        record("2026-11-12T10:00:00+00:00", 25),  # after "today"
    )
    p = goal_progress(s, 120, WEDNESDAY, UTC)
    assert (p.first_day, p.last_day) == (MONDAY, SUNDAY)
    assert p.done == 62
    assert p.remaining == 58
    assert p.percent == 51
    assert p.days_left == 5
    assert not p.met


def test_session_across_sunday_midnight_is_split_between_weeks():
    s = sessions(record("2026-11-08T23:50:00+00:00", 25))
    assert goal_progress(s, 60, MONDAY, UTC).minutes == pytest.approx(15)


def test_week_boundary_uses_local_time():
    # 03:00Z on Monday is still Sunday evening in UTC-5.
    s = sessions(record("2026-11-09T03:00:00+00:00", 25))
    assert goal_progress(s, 60, MONDAY, UTC).done == 25
    assert goal_progress(s, 60, MONDAY, timezone(timedelta(hours=-5))).done == 0


def test_percent_rounds_down_and_met_matches_display():
    almost = goal_progress(sessions(record("2026-11-09T10:00:00+00:00", 598.6)), 600, MONDAY, UTC)
    assert (almost.done, almost.percent, almost.met) == (599, 99, False)
    rounded = goal_progress(sessions(record("2026-11-09T10:00:00+00:00", 599.6)), 600, MONDAY, UTC)
    assert (rounded.done, rounded.percent, rounded.met, rounded.remaining) == (600, 100, True, 0)
    over = goal_progress(sessions(record("2026-11-09T00:00:00+00:00", 900)), 600, MONDAY, UTC)
    assert (over.percent, over.remaining) == (150, 0)


def test_last_day_of_week_has_one_day_left():
    assert goal_progress([], 60, SUNDAY, UTC).days_left == 1


def test_goal_must_be_positive():
    with pytest.raises(ValueError):
        goal_progress([], 0, MONDAY, UTC)


# ------------------------------------------------------------ stats


def test_stats_without_goal_has_no_goal_line(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T09:00:00+00:00")])
    code, out, _ = run("stats")
    assert code == 0
    assert "Week goal" not in out


def test_stats_shows_goal_progress(run, isolated_home):
    write_log(isolated_home, [
        record("2026-11-08T09:00:00+00:00", 300),  # previous week
        record("2026-11-09T09:00:00+00:00", 90),
    ])
    assert run("config", "set", "weekly_goal", "600")[0] == 0
    code, out, _ = run("stats", "--days", "3", "--color", "never")
    assert code == 0
    line = out.splitlines()[-1]
    assert line.startswith("Week goal   ")
    assert line.endswith("1h 30m of 10h 00m (15%), 8h 30m to go, 7 day(s) left")
    bar = line.split()[2]
    assert len(bar) == 20
    assert bar.count(bar[0]) == 3  # 15% of 20 cells


def test_stats_goal_met(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T09:00:00+00:00", 125)])
    run("config", "set", "weekly_goal", "120")
    code, out, _ = run("stats", "--color", "never")
    assert code == 0
    assert out.splitlines()[-1].endswith("2h 05m of 2h 00m (104%), goal met")


def test_stats_by_task_has_no_goal_line(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T09:00:00+00:00")])
    run("config", "set", "weekly_goal", "120")
    code, out, _ = run("stats", "--by", "task")
    assert code == 0
    assert "Week goal" not in out


# ------------------------------------------------------------ start


class InstantClock:
    """Fake clock: sleeping advances time without waiting."""

    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


# A Monday morning, so the blocks the timer logs land in the current week.
SESSION_START = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


def test_start_prints_week_summary_including_new_blocks(run, isolated_home):
    write_log(isolated_home, [
        record("2026-11-08T09:00:00+00:00", 100),  # previous week, ignored
        record("2026-11-09T07:00:00+00:00", 50),
    ])
    run("config", "set", "weekly_goal", "300")
    clock = InstantClock(SESSION_START.timestamp())
    code, out, _ = run("start", "--cycles", "2", "--no-bell", clock=clock,
                       now=lambda: datetime.fromtimestamp(clock(), UTC))
    assert code == 0
    assert out.splitlines()[-1] == (
        "This week: 1h 40m of 5h 00m goal (33%), 3h 20m to go, 7 day(s) left."
    )


def test_start_summary_when_goal_met(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T07:00:00+00:00", 100)])
    run("config", "set", "weekly_goal", "120")
    clock = InstantClock(SESSION_START.timestamp())
    code, out, _ = run("start", "--cycles", "1", "--no-bell", clock=clock,
                       now=lambda: datetime.fromtimestamp(clock(), UTC))
    assert code == 0
    assert out.splitlines()[-1] == "This week: 2h 05m of 2h 00m goal (104%), goal met."


def test_start_without_goal_prints_no_summary(run, isolated_home):
    clock = InstantClock(SESSION_START.timestamp())
    code, out, _ = run("start", "--seconds", "--work", "2", "--short", "1", "--long", "1",
                       "--cycles", "1", "--no-bell", clock=clock)
    assert code == 0
    assert "This week" not in out


def test_start_summary_skips_corrupt_log_lines_quietly(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T07:00:00+00:00", 30)])
    with open(isolated_home / "sessions.jsonl", "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    run("config", "set", "weekly_goal", "600")
    clock = InstantClock(SESSION_START.timestamp())
    code, out, err = run("start", "--cycles", "1", "--no-bell", clock=clock,
                         now=lambda: datetime.fromtimestamp(clock(), UTC))
    assert code == 0
    assert "warning" not in err
    assert out.splitlines()[-1].startswith("This week: 55m of 10h 00m goal (9%)")
