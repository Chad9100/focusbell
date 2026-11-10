from datetime import datetime, timedelta, timezone

from focusbell.ics import to_ics
from focusbell.log import Session


def make(start="2026-11-09T09:00:00+00:00", minutes=25.0, label="thesis", status="completed", **kw):
    s = datetime.fromisoformat(start)
    return Session(s, s + timedelta(minutes=minutes), minutes, kw.pop("planned", 25.0), label, status, **kw)


def unfolded(text):
    return text.replace("\r\n ", "").split("\r\n")


def test_calendar_structure_and_crlf():
    text = to_ics([make()])
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    lines = unfolded(text)
    assert lines[0] == "BEGIN:VCALENDAR" and "VERSION:2.0" in lines
    assert "DTSTART:20261109T090000Z" in lines
    assert "DTEND:20261109T092500Z" in lines
    assert "SUMMARY:Focus: thesis" in lines
    assert "DESCRIPTION:Completed: 25 min focused of 25 planned" in lines


def test_times_converted_to_utc():
    tz = timezone(timedelta(hours=-8))
    s = datetime(2026, 11, 9, 9, 0, tzinfo=tz)
    sess = Session(s, s + timedelta(minutes=25), 25.0, 25.0, None, "interrupted")
    lines = unfolded(to_ics([sess]))
    assert "DTSTART:20261109T170000Z" in lines
    assert "SUMMARY:Focus" in lines
    assert "DESCRIPTION:Interrupted: 25 min focused of 25 planned" in lines


def test_text_escaped_and_long_lines_folded():
    label = "a, b; c\\d " + "x" * 120 + " é"
    text = to_ics([make(label=label)])
    assert all(len(l.encode("utf-8")) <= 75 for l in text.split("\r\n"))
    summary = [l for l in unfolded(text) if l.startswith("SUMMARY:")][0]
    assert summary == "SUMMARY:Focus: a\\, b\\; c\\\\d " + "x" * 120 + " é"


def test_unique_uids_for_same_start_and_pauses_described():
    text = to_ics([make(pauses=2, paused_minutes=3.5), make()])
    uids = [l for l in unfolded(text) if l.startswith("UID:")]
    assert len(set(uids)) == 2
    assert "DESCRIPTION:Completed: 25 min focused of 25 planned\\; paused 2x (3.5 min)" in unfolded(text)


def test_empty_log_is_valid_calendar():
    assert to_ics([]).count("VEVENT") == 0
    assert to_ics([]).startswith("BEGIN:VCALENDAR\r\n")
