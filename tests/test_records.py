import json
from datetime import date, timedelta, timezone

from focusbell.log import parse_record
from focusbell.stats import longest_streak, records

UTC = timezone.utc
MONDAY = date(2026, 11, 9)


def record(start, minutes=25.0, status="completed"):
    return {"start": start, "minutes": minutes, "planned_minutes": 25.0,
            "label": None, "status": status}


def sessions(*recs):
    return [parse_record(r) for r in recs]


def write_log(home, recs):
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "sessions.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def days(*isodates):
    return [date.fromisoformat(d) for d in isodates]


# ------------------------------------------------------------ longest streak


def test_longest_streak_of_nothing_is_zero():
    assert longest_streak([]) == (0, None, None)


def test_longest_streak_finds_the_longest_run():
    active = days("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05", "2026-10-06")
    assert longest_streak(active) == (3, date(2026, 10, 1), date(2026, 10, 3))


def test_longest_streak_tie_goes_to_most_recent_run():
    active = days("2026-10-01", "2026-10-02", "2026-10-10", "2026-10-11")
    assert longest_streak(active) == (2, date(2026, 10, 10), date(2026, 10, 11))


def test_longest_streak_ignores_order_and_duplicates():
    active = days("2026-10-03", "2026-10-01", "2026-10-02", "2026-10-02")
    assert longest_streak(active) == (3, date(2026, 10, 1), date(2026, 10, 3))


def test_longest_streak_crosses_month_end():
    active = days("2026-10-30", "2026-10-31", "2026-11-01")
    assert longest_streak(active)[0] == 3


# ------------------------------------------------------------ records


def test_records_of_empty_log():
    r = records([], MONDAY, UTC)
    assert (r.streak_days, r.streak_first, r.week_first, r.week_minutes) == (0, None, None, 0)
    assert not r.streak_current and not r.week_current


def test_best_week_is_found_across_the_whole_log():
    s = sessions(
        record("2026-10-12T09:00:00+00:00", 100),  # week of 10-12
        record("2026-10-14T09:00:00+00:00", 200),
        record("2026-10-20T09:00:00+00:00", 250),  # week of 10-19
        record("2026-11-09T09:00:00+00:00", 30),  # this week
    )
    r = records(s, MONDAY, UTC)
    assert (r.week_first, r.week_minutes, r.week_current) == (date(2026, 10, 12), 300, False)


def test_best_week_can_be_the_current_one_and_ties_go_recent():
    s = sessions(
        record("2026-11-02T09:00:00+00:00", 60),
        record("2026-11-09T09:00:00+00:00", 60),
    )
    r = records(s, MONDAY, UTC)
    assert (r.week_first, r.week_current) == (MONDAY, True)


def test_week_split_at_local_sunday_midnight():
    # 23:50 Sunday to 00:15 Monday: 10 minutes count for each week's side.
    s = sessions(record("2026-11-08T23:50:00+00:00", 25))
    r = records(s, MONDAY, UTC)
    assert (r.week_first, round(r.week_minutes)) == (MONDAY, 15)
    # In UTC-5 the whole block is on Sunday evening, the previous week.
    r = records(s, MONDAY, timezone(timedelta(hours=-5)))
    assert (r.week_first, round(r.week_minutes)) == (date(2026, 11, 2), 25)


def test_days_after_today_are_ignored():
    s = sessions(record("2026-11-09T09:00:00+00:00", 25), record("2026-11-10T09:00:00+00:00", 500),
                 record("2026-11-11T09:00:00+00:00", 25))
    r = records(s, MONDAY, UTC)
    assert (r.streak_days, r.week_minutes) == (1, 25)


def test_zero_minute_sessions_do_not_count():
    s = sessions(record("2026-11-08T09:00:00+00:00", 0), record("2026-11-09T09:00:00+00:00", 0))
    r = records(s, MONDAY, UTC)
    assert (r.streak_days, r.week_first) == (0, None)


def test_best_streak_is_current_when_still_going_from_yesterday():
    s = sessions(record("2026-11-07T09:00:00+00:00"), record("2026-11-08T09:00:00+00:00"))
    r = records(s, MONDAY, UTC)
    assert (r.streak_days, r.streak_last, r.streak_current) == (2, date(2026, 11, 8), True)


def test_old_best_streak_is_not_current():
    s = sessions(
        record("2026-10-01T09:00:00+00:00"), record("2026-10-02T09:00:00+00:00"),
        record("2026-10-03T09:00:00+00:00"), record("2026-11-09T09:00:00+00:00"),
    )
    r = records(s, MONDAY, UTC)
    assert (r.streak_days, r.streak_first, r.streak_current) == (3, date(2026, 10, 1), False)


# ------------------------------------------------------------ stats output


def test_stats_shows_best_streak_and_week_outside_the_window(run, isolated_home):
    write_log(isolated_home, [
        record("2026-10-05T09:00:00+00:00", 120),
        record("2026-10-06T09:00:00+00:00", 120),
        record("2026-10-07T09:00:00+00:00", 140),
        record("2026-11-08T09:00:00+00:00", 25),
        record("2026-11-09T09:00:00+00:00", 25),
    ])
    code, out, _ = run("stats", "--days", "3", "--color", "never")
    assert code == 0
    lines = out.splitlines()
    i = lines.index("Streak      2 day(s)")
    assert lines[i + 1] == "Best streak 3 day(s), 2026-10-05 to 2026-10-07"
    assert lines[i + 2] == "Best week   6h 20m, week of 2026-10-05"


def test_stats_marks_current_records(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T09:00:00+00:00", 50)])
    code, out, _ = run("stats", "--color", "never")
    assert code == 0
    assert "Best streak 1 day(s), 2026-11-09 (current)" in out.splitlines()
    assert "Best week   50m, week of 2026-11-09 (this week)" in out.splitlines()


def test_stats_on_empty_log(run):
    code, out, _ = run("stats", "--color", "never")
    assert code == 0
    assert "Best streak 0 day(s)" in out.splitlines()
    assert "Best week   -" in out.splitlines()


def test_records_come_before_goal_line(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T09:00:00+00:00", 50)])
    run("config", "set", "weekly_goal", "600")
    code, out, _ = run("stats", "--color", "never")
    lines = out.splitlines()
    assert lines[-3].startswith("Best streak ")
    assert lines[-2].startswith("Best week ")
    assert lines[-1].startswith("Week goal ")


def test_stats_by_task_has_no_records(run, isolated_home):
    write_log(isolated_home, [record("2026-11-09T09:00:00+00:00")])
    code, out, _ = run("stats", "--by", "task")
    assert code == 0
    assert "Best streak" not in out and "Best week" not in out
