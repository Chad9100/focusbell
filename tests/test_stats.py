from datetime import date, timedelta, timezone

import pytest

from conftest import rec
from focusbell.log import parse_record
from focusbell.stats import compute_stats, current_streak, minutes_by_day

UTC = timezone.utc
NEW_YORK_WINTER = timezone(timedelta(hours=-5))
TOKYO = timezone(timedelta(hours=9))


def sessions(*records):
    return [parse_record(r) for r in records]


def test_minutes_by_day_sums_same_day():
    s = sessions(rec("2026-11-05T09:00:00+00:00", 25), rec("2026-11-05T14:00:00+00:00", 10))
    assert minutes_by_day(s, UTC) == {date(2026, 11, 5): 35}


def test_session_across_midnight_is_split():
    s = sessions(rec("2026-11-05T23:50:00+00:00", 25))
    assert minutes_by_day(s, UTC) == pytest.approx({date(2026, 11, 5): 10, date(2026, 11, 6): 15})


def test_split_happens_at_local_midnight_not_utc():
    # 04:50Z..05:15Z is 23:50..00:15 in UTC-5
    s = sessions(rec("2026-11-06T04:50:00+00:00", 25))
    assert minutes_by_day(s, UTC) == {date(2026, 11, 6): 25}
    assert minutes_by_day(s, NEW_YORK_WINTER) == pytest.approx(
        {date(2026, 11, 5): 10, date(2026, 11, 6): 15}
    )


@pytest.mark.parametrize(
    "tz,expected_day",
    [(UTC, date(2026, 11, 9)), (NEW_YORK_WINTER, date(2026, 11, 8)), (TOKYO, date(2026, 11, 9))],
)
def test_day_depends_on_time_zone(tz, expected_day):
    s = sessions(rec("2026-11-09T02:00:00+00:00", 25))
    assert minutes_by_day(s, tz) == {expected_day: 25}


def test_multi_day_session_spans_three_days():
    s = sessions(rec("2026-11-05T23:00:00+00:00", 26 * 60))
    days = minutes_by_day(s, UTC)
    assert days == pytest.approx(
        {date(2026, 11, 5): 60, date(2026, 11, 6): 1440, date(2026, 11, 7): 60}
    )


def test_zero_minute_session_adds_no_time():
    assert minutes_by_day(sessions(rec("2026-11-05T09:00:00+00:00", 0)), UTC) == {}


# ------------------------------------------------------------ streaks

TODAY = date(2026, 11, 9)


def days_ago(*offsets):
    return [TODAY - timedelta(days=n) for n in offsets]


def test_streak_counts_consecutive_days_ending_today():
    assert current_streak(days_ago(0, 1, 2, 4, 5), TODAY) == 3


def test_streak_survives_until_today_has_a_session():
    assert current_streak(days_ago(1, 2), TODAY) == 2


def test_streak_broken_by_gap():
    assert current_streak(days_ago(2, 3, 4), TODAY) == 0


def test_streak_empty():
    assert current_streak([], TODAY) == 0


def test_streak_across_month_boundary():
    active = [date(2026, 11, 1), date(2026, 10, 31), date(2026, 10, 30)]
    assert current_streak(active, date(2026, 11, 1)) == 3


# ------------------------------------------------------------ compute_stats


def demo():
    return sessions(
        rec("2026-11-09T09:00:00+00:00", 25, "thesis"),
        rec("2026-11-09T10:00:00+00:00", 12, "thesis", "interrupted"),
        rec("2026-11-08T09:00:00+00:00", 25, "email"),
        rec("2026-11-07T09:00:00+00:00", 50, "code"),
        rec("2026-11-01T09:00:00+00:00", 25, "old"),  # outside a 7-day window
    )


def test_compute_stats_window_and_per_day():
    st = compute_stats(demo(), 7, TODAY, UTC)
    assert st.first_day == date(2026, 11, 3) and st.last_day == TODAY
    assert st.per_day[0][0] == date(2026, 11, 3)
    assert len(st.per_day) == 7
    assert dict(st.per_day)[TODAY] == 37
    assert dict(st.per_day)[date(2026, 11, 4)] == 0
    assert st.total_minutes == 37 + 25 + 50


def test_compute_stats_completion_rate():
    st = compute_stats(demo(), 7, TODAY, UTC)
    assert (st.sessions, st.completed, st.interrupted) == (4, 3, 1)
    assert st.completion_rate == 0.75


def test_completion_rate_none_without_sessions():
    st = compute_stats([], 7, TODAY, UTC)
    assert st.completion_rate is None and st.total_minutes == 0 and st.streak == 0


def test_top_labels_by_minutes_limited():
    st = compute_stats(demo(), 7, TODAY, UTC, top=2)
    assert st.top_labels == [("code", 50), ("thesis", 37)]


def test_streak_uses_all_history_not_just_window():
    many = sessions(*[rec(f"2026-11-{d:02d}T09:00:00+00:00") for d in range(1, 10)])
    assert compute_stats(many, 3, TODAY, UTC).streak == 9


def test_window_respects_time_zone():
    s = sessions(rec("2026-11-03T02:00:00+00:00", 25))  # still Nov 2 in New York
    assert compute_stats(s, 7, TODAY, UTC).sessions == 1
    assert compute_stats(s, 7, TODAY, NEW_YORK_WINTER).sessions == 0


def test_days_must_be_positive():
    with pytest.raises(ValueError):
        compute_stats([], 0, TODAY, UTC)
