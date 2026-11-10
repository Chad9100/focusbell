"""`note --start`, and notes in the HTML report and ics description."""

import io
import json
from datetime import timezone

from focusbell.cli import main


def rec(start, label="thesis", **extra):
    hour = start[11:13]
    data = {"start": start, "end": f"2026-11-09T{hour}:25:00+00:00", "minutes": 25.0,
            "planned_minutes": 25.0, "label": label, "status": "completed"}
    data.update(extra)
    return data


def setup(tmp_path, records):
    (tmp_path / "sessions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return {"FOCUSBELL_HOME": str(tmp_path)}


def run(env, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, environ=env, tz=timezone.utc)
    return code, out.getvalue(), err.getvalue()


def lines(tmp_path):
    text = (tmp_path / "sessions.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines()]


def test_start_picks_an_earlier_session(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00"),
                           rec("2026-11-09T10:00:00+00:00", label="email")])
    code, out, _ = run(env, "note", "--start", "2026-11-09 09:00", "first", "one")
    assert code == 0 and "09:00" in out
    first, second = lines(tmp_path)
    assert first["note"] == "first one" and "note" not in second


def test_start_accepts_t_separator(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00")])
    assert run(env, "note", "--start", "2026-11-09T09:00", "x")[0] == 0
    assert lines(tmp_path)[0]["note"] == "x"


def test_start_without_match_is_an_error_and_log_unchanged(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00")])
    before = (tmp_path / "sessions.jsonl").read_bytes()
    code, _, err = run(env, "note", "--start", "2026-11-09 09:01", "x")
    assert code != 0 and "no session started at 2026-11-09 09:01" in err
    assert (tmp_path / "sessions.jsonl").read_bytes() == before


def test_start_bad_format_is_usage_error(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00")])
    assert run(env, "note", "--start", "yesterday", "x")[0] == 2


def test_ics_description_includes_note(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00", note="stuck; on, ch.2")])
    code, out, _ = run(env, "export", "--format", "ics")
    assert code == 0
    assert "\\nstuck\\; on\\, ch.2" in out.replace("\r\n ", "")


def test_ics_without_note_unchanged(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00")])
    out = run(env, "export", "--format", "ics")[1]
    assert "\\n" not in out.replace("\r\n ", "")


def test_report_note_column_escaped(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00", note="<b>hi</b> & bye")])
    out_file = tmp_path / "r.html"
    code, _, _ = run(env, "report", "--html", str(out_file))
    assert code == 0
    html = out_file.read_text(encoding="utf-8")
    assert "<th>Note</th>" in html
    assert "&lt;b&gt;hi&lt;/b&gt; &amp; bye" in html and "<b>hi</b>" not in html


def test_report_has_no_note_column_without_notes(tmp_path):
    env = setup(tmp_path, [rec("2026-11-09T09:00:00+00:00")])
    out_file = tmp_path / "r.html"
    run(env, "report", "--html", str(out_file))
    assert "<th>Note</th>" not in out_file.read_text(encoding="utf-8")
