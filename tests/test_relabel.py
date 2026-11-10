"""`focusbell relabel`."""

import io
import json
from datetime import timezone

from focusbell.cli import main


def rec(start, label="thesis"):
    hour = start[11:13]
    return {"start": start, "end": f"2026-11-09T{hour}:25:00+00:00", "minutes": 25.0,
            "planned_minutes": 25.0, "label": label, "status": "completed"}


def setup(tmp_path, text):
    (tmp_path / "sessions.jsonl").write_bytes(text.encode("utf-8"))
    return {"FOCUSBELL_HOME": str(tmp_path)}


def run(env, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, environ=env, tz=timezone.utc)
    return code, out.getvalue(), err.getvalue()


def read(tmp_path):
    return (tmp_path / "sessions.jsonl").read_bytes()


def test_relabels_latest(tmp_path):
    a, b = rec("2026-11-09T09:00:00+00:00"), rec("2026-11-09T10:00:00+00:00", "emial")
    env = setup(tmp_path, json.dumps(a) + "\n" + json.dumps(b) + "\n")
    code, out, _ = run(env, "relabel", "email", "triage")
    assert code == 0 and "emial -> email triage" in out and "10:00" in out
    lines = read(tmp_path).decode().splitlines()
    assert json.loads(lines[0]) == a
    assert json.loads(lines[1])["label"] == "email triage"


def test_start_picks_earlier_session(tmp_path):
    env = setup(tmp_path, json.dumps(rec("2026-11-09T09:00:00+00:00")) + "\n"
                + json.dumps(rec("2026-11-09T10:00:00+00:00")) + "\n")
    assert run(env, "relabel", "--start", "2026-11-09 09:00", "x")[0] == 0
    first, second = [json.loads(x) for x in read(tmp_path).decode().splitlines()]
    assert first["label"] == "x" and second["label"] == "thesis"


def test_unlabelled_session_and_untouched_bytes(tmp_path):
    first = '{"start":"2026-11-09T09:00:00+00:00","minutes":5}\r\n'
    corrupt = "not json\n"
    env = setup(tmp_path, corrupt + first)
    code, out, _ = run(env, "relabel", "new")
    assert code == 0 and "no label -> new" in out
    data = read(tmp_path)
    assert data.startswith(corrupt.encode())
    assert data.endswith(b"\r\n") and b'"label": "new"' in data


def test_no_match_leaves_log_unchanged(tmp_path):
    env = setup(tmp_path, json.dumps(rec("2026-11-09T09:00:00+00:00")) + "\n")
    before = read(tmp_path)
    code, _, err = run(env, "relabel", "--start", "2026-11-09 09:01", "x")
    assert code != 0 and "no session started at" in err
    assert read(tmp_path) == before
    assert not (tmp_path / "sessions.jsonl.tmp").exists()


def test_empty_log_and_empty_label(tmp_path):
    env = {"FOCUSBELL_HOME": str(tmp_path)}
    code, _, err = run(env, "relabel", "x")
    assert code == 1 and "nothing to relabel" in err
    env = setup(tmp_path, json.dumps(rec("2026-11-09T09:00:00+00:00")) + "\n")
    assert run(env, "relabel", "  ")[0] == 2
