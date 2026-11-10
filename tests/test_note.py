"""`focusbell note`: attach text to the most recent session."""

import csv
import io
import json

from focusbell.cli import main
from focusbell.log import parse_record


def rec(start, label="thesis", **extra):
    hour = start[11:13]
    data = {"start": start, "end": f"2026-11-09T{hour}:25:00+00:00", "minutes": 25.0,
            "planned_minutes": 25.0, "label": label, "status": "completed"}
    data.update(extra)
    return data


def setup(tmp_path, lines):
    (tmp_path / "sessions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"FOCUSBELL_HOME": str(tmp_path)}


def run(env, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, environ=env, tz=None)
    return code, out.getvalue(), err.getvalue()


def test_note_goes_on_latest_session_only(tmp_path):
    a = json.dumps(rec("2026-11-09T09:00:00+00:00"))
    b = json.dumps(rec("2026-11-09T10:00:00+00:00", label="email"))
    env = setup(tmp_path, [a, b])
    code, out, _ = run(env, "note", "stuck", "on", "ch.2")
    assert code == 0 and "stuck on ch.2" in out and "email" in out
    lines = (tmp_path / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines[0] == a
    assert json.loads(lines[1])["note"] == "stuck on ch.2"


def test_latest_is_by_start_time_not_line_order(tmp_path):
    late = json.dumps(rec("2026-11-09T10:00:00+00:00"))
    early = json.dumps(rec("2026-11-09T09:00:00+00:00"))
    env = setup(tmp_path, [late, early])
    run(env, "note", "x")
    lines = (tmp_path / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    assert "note" in json.loads(lines[0]) and "note" not in json.loads(lines[1])


def test_corrupt_lines_preserved_and_note_replaced(tmp_path):
    first = json.dumps(rec("2026-11-09T09:00:00+00:00", note="old"))
    env = setup(tmp_path, ["{not json", first])
    assert run(env, "note", "new")[0] == 0
    lines = (tmp_path / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "{not json"
    assert json.loads(lines[1])["note"] == "new"
    assert not (tmp_path / "sessions.jsonl.tmp").exists()


def test_no_sessions_is_an_error(tmp_path):
    code, _, err = run({"FOCUSBELL_HOME": str(tmp_path)}, "note", "hi")
    assert code == 1 and "no sessions" in err


def test_blank_note_refused(tmp_path):
    env = setup(tmp_path, [json.dumps(rec("2026-11-09T09:00:00+00:00"))])
    code, _, err = run(env, "note", "   ")
    assert code == 2 and "empty" in err


def test_bad_note_type_is_a_corrupt_line():
    try:
        parse_record(rec("2026-11-09T09:00:00+00:00", note=5))
    except ValueError as exc:
        assert "note" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_log_shows_note_column_only_when_present(tmp_path):
    env = setup(tmp_path, [json.dumps(rec("2026-11-09T09:00:00+00:00"))])
    assert "Note" not in run(env, "log")[1]
    run(env, "note", "good flow")
    out = run(env, "log")[1]
    assert "Note" in out and "good flow" in out


def test_export_includes_note(tmp_path):
    env = setup(tmp_path, [json.dumps(rec("2026-11-09T09:00:00+00:00")),
                           json.dumps(rec("2026-11-09T10:00:00+00:00"))])
    run(env, "note", "a, b")
    rows = list(csv.DictReader(io.StringIO(run(env, "export")[1])))
    assert [r["note"] for r in rows] == ["", "a, b"]
    data = json.loads(run(env, "export", "--format", "json")[1])
    assert "note" not in data[0] and data[1]["note"] == "a, b"
