import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import rec, write_log
from focusbell.log import append_record, data_dir, log_path, parse_record, read_sessions


# ------------------------------------------------------------ data dir


def test_focusbell_home_overrides_everything(tmp_path):
    env = {"FOCUSBELL_HOME": str(tmp_path), "APPDATA": "C:/x", "XDG_DATA_HOME": "/y"}
    assert data_dir(env, "win32") == tmp_path
    assert data_dir(env, "linux") == tmp_path


def test_windows_uses_appdata():
    assert data_dir({"APPDATA": "C:/Users/me/AppData/Roaming"}, "win32") == Path(
        "C:/Users/me/AppData/Roaming/focusbell"
    )


def test_linux_uses_xdg_data_home():
    assert data_dir({"XDG_DATA_HOME": "/data"}, "linux") == Path("/data/focusbell")


def test_linux_falls_back_to_local_share():
    assert data_dir({}, "linux") == Path.home() / ".local" / "share" / "focusbell"


def test_log_path_lives_in_data_dir(tmp_path):
    assert log_path({"FOCUSBELL_HOME": str(tmp_path)}) == tmp_path / "sessions.jsonl"


# ------------------------------------------------------------ append / read


def test_append_creates_directory_and_one_line_per_record(tmp_path):
    path = tmp_path / "deep" / "dir" / "sessions.jsonl"
    append_record(path, rec("2026-11-01T09:00:00+00:00"))
    append_record(path, rec("2026-11-01T10:00:00+00:00"))
    lines = path.read_bytes().split(b"\n")
    assert len(lines) == 3 and lines[-1] == b""
    assert b"\r" not in path.read_bytes()


def test_round_trip(tmp_path):
    path = tmp_path / "s.jsonl"
    append_record(path, rec("2026-11-01T09:00:00+00:00", 12.5, "deep work", "interrupted"))
    (s,) = read_sessions(path)
    assert s.start == datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    assert s.end == s.start + timedelta(minutes=12.5)
    assert (s.minutes, s.label, s.status, s.planned_minutes) == (12.5, "deep work", "interrupted", 25.0)


def test_unicode_label_round_trip(tmp_path):
    path = tmp_path / "s.jsonl"
    append_record(path, rec("2026-11-01T09:00:00+00:00", label="Übung ✓"))
    assert read_sessions(path)[0].label == "Übung ✓"


def test_missing_log_is_empty(tmp_path):
    assert read_sessions(tmp_path / "nope.jsonl") == []


@pytest.mark.parametrize(
    "bad",
    [
        "{not json",
        "[1, 2, 3]",
        '"just a string"',
        json.dumps({"minutes": 25}),
        json.dumps(rec("yesterday-ish")),
        json.dumps(rec("2026-11-01T09:00:00+00:00", minutes="25")),
        json.dumps(rec("2026-11-01T09:00:00+00:00", minutes=-1)),
        json.dumps(rec("2026-11-01T09:00:00+00:00", minutes=True)),
        json.dumps(rec("2026-11-01T09:00:00+00:00", status="paused")),
        json.dumps({**rec("2026-11-01T09:00:00+00:00"), "label": 42}),
    ],
)
def test_corrupt_lines_are_skipped_with_warning(tmp_path, bad):
    path = write_log(
        tmp_path,
        [rec("2026-11-01T09:00:00+00:00")],
        extra_lines=[bad, json.dumps(rec("2026-11-02T09:00:00+00:00"))],
    )
    warnings = []
    sessions = read_sessions(path, warnings.append)
    assert len(sessions) == 2
    assert len(warnings) == 1 and "line 2" in warnings[0]


def test_truncated_last_line_is_skipped(tmp_path):
    path = write_log(tmp_path, [rec("2026-11-01T09:00:00+00:00")])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"start": "2026-11-0')
    warnings = []
    assert len(read_sessions(path, warnings.append)) == 1
    assert len(warnings) == 1


def test_blank_lines_are_ignored_silently(tmp_path):
    path = write_log(tmp_path, [rec("2026-11-01T09:00:00+00:00")], extra_lines=["", "   "])
    warnings = []
    assert len(read_sessions(path, warnings.append)) == 1
    assert warnings == []


def test_z_suffix_and_naive_timestamps_are_utc():
    z = parse_record(rec("2026-11-01T09:00:00Z"))
    naive = parse_record(rec("2026-11-01T09:00:00"))
    assert z.start == naive.start == datetime(2026, 11, 1, 9, tzinfo=timezone.utc)


def test_offset_timestamps_are_preserved():
    s = parse_record(rec("2026-11-01T09:00:00+05:30"))
    assert s.start == datetime(2026, 11, 1, 3, 30, tzinfo=timezone.utc)


def test_missing_status_defaults_to_completed():
    data = rec("2026-11-01T09:00:00+00:00")
    del data["status"]
    assert parse_record(data).status == "completed"


def test_sessions_are_sorted_by_start(tmp_path):
    path = write_log(tmp_path, [rec("2026-11-03T09:00:00+00:00"), rec("2026-11-01T09:00:00+00:00")])
    assert [s.start.day for s in read_sessions(path)] == [1, 3]


def test_utf8_bom_does_not_corrupt_first_line(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(rec("2026-11-01T09:00:00+00:00")).encode() + b"\n")
    warnings = []
    assert len(read_sessions(path, warnings.append)) == 1
    assert warnings == []
