import io
import json
import re
from datetime import date, datetime, timedelta, timezone

from focusbell.cli import main
from focusbell.log import parse_record
from focusbell.report import _level, render_html

TODAY = date(2026, 11, 9)  # a Monday
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def session(start, minutes=25.0, label=None, status="completed"):
    return parse_record({"start": start, "minutes": minutes, "planned_minutes": 25.0,
                         "label": label, "status": status})


def write_sessions(home, records):
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "sessions.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def run_cli(home, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, environ={"FOCUSBELL_HOME": str(home)},
                clock=lambda: 0.0, sleep=lambda s: None, now=lambda: NOW, tz=timezone.utc)
    return code, out.getvalue(), err.getvalue()


SESSIONS = [
    session("2026-11-09T09:00:00+00:00", 50, "thesis"),
    session("2026-11-08T09:00:00+00:00", 25, "email"),
    session("2026-11-08T10:00:00+00:00", 10, "thesis", "interrupted"),
    session("2026-11-02T09:00:00+00:00", 25),
    session("2026-01-01T09:00:00+00:00", 25, "too old"),
]


def test_level_scales_to_busiest_day():
    assert _level(0, 100) == 0
    assert _level(1, 100) == 1
    assert _level(25, 100) == 1
    assert _level(26, 100) == 2
    assert _level(75, 100) == 3
    assert _level(100, 100) == 4
    assert _level(10, 0) == 0


def test_page_is_self_contained():
    page = render_html(SESSIONS, TODAY, 28, timezone.utc)
    assert page.startswith("<!DOCTYPE html>")
    assert page.rstrip().endswith("</html>")
    assert "<script" not in page
    assert not re.search(r"""(src|href)\s*=|url\(|@import|https?://""", page)


def test_totals_and_range():
    page = render_html(SESSIONS, TODAY, 28, timezone.utc, generated="2026-11-09 12:00")
    assert "2026-10-13 to 2026-11-09 (28 day(s)), generated 2026-11-09 12:00" in page
    assert "<b>1h 50m</b>" in page  # 50 + 25 + 10 + 25, the January one is outside
    assert "<b>4</b><span class=\"muted\">session(s)" in page
    assert "<b>3</b><span class=\"muted\">completed" in page
    assert "<b>3</b><span class=\"muted\">active day(s)" in page
    assert "too old" not in page


def test_heat_map_cells():
    page = render_html(SESSIONS, TODAY, 28, timezone.utc)
    cells = re.findall(r'<td class="l(\d)" title="([^"]+)"></td>', page)
    assert len(cells) == 28
    tips = dict((t.split(" ")[0], int(lvl)) for lvl, t in cells)
    assert tips["2026-11-09"] == 4  # busiest day, 50m
    assert tips["2026-11-08"] == 3  # 35m of 50m
    assert tips["2026-11-02"] == 2  # 25m of 50m
    assert tips["2026-11-01"] == 0
    assert '<td class="l4" title="2026-11-09 Mon: 50m"></td>' in page
    # 2026-10-13 is a Tuesday, so that week's Monday is outside the range.
    assert page.count('<td class="out"></td>') == 1 + 6  # Mon 10-12 before, Tue..Sun after today
    assert "busiest day 50m" in page


def test_by_label_and_session_table():
    page = render_html(SESSIONS, TODAY, 28, timezone.utc)
    labels = page.split("<h2>By label</h2>")[1].split("<h2>Sessions</h2>")[0]
    order = [labels.index(x) for x in ("thesis", "email", "(no label)")]
    assert order == sorted(order)
    assert "<td class=\"num\">1h 00m</td>" in labels
    rows = page.split("<h2>Sessions</h2>")[1]
    assert rows.index("2026-11-09") < rows.index("2026-11-02")  # newest first
    assert '<span class="interrupted">interrupted</span>' in rows
    assert "<td>09:00</td><td>09:50</td>" in rows


def test_labels_are_escaped():
    page = render_html([session("2026-11-09T09:00:00+00:00", label='<b>"x"&</b>')],
                       TODAY, 7, timezone.utc)
    assert '<b>"x"&</b>' not in page
    assert "&lt;b&gt;&quot;x&quot;&amp;&lt;/b&gt;" in page


def test_empty_log():
    page = render_html([], TODAY, 7, timezone.utc)
    assert page.count("No sessions in this period.") == 2
    assert "busiest day 0m" in page


def test_local_timezone_moves_days():
    tz = timezone(timedelta(hours=-8))
    page = render_html([session("2026-11-09T05:00:00+00:00", 25)], TODAY, 7, tz)
    assert 'title="2026-11-08 Sun: 25m"' in page


def test_cli_writes_file(tmp_path):
    home = tmp_path / "home"
    write_sessions(home, [{"start": "2026-11-09T09:00:00+00:00", "minutes": 25,
                           "planned_minutes": 25, "label": "thesis", "status": "completed"}])
    target = tmp_path / "out.html"
    code, out, err = run_cli(home, "report", "--html", str(target), "--days", "14")
    assert code == 0, err
    assert out == ""
    assert f"Wrote report for 14 day(s) to {target}" in err
    page = target.read_text(encoding="utf-8")
    assert "thesis" in page and "2026-10-27 to 2026-11-09" in page
    assert "generated 2026-11-09 12:00" in page


def test_cli_stdout_and_default_days(tmp_path):
    code, out, err = run_cli(tmp_path / "home", "report", "--html", "-")
    assert code == 0, err
    assert out.startswith("<!DOCTYPE html>")
    assert "(182 day(s))" in out


def test_cli_errors(tmp_path):
    home = tmp_path / "home"
    code, _, err = run_cli(home, "report")
    assert code == 2
    code, _, err = run_cli(home, "report", "--html", "-", "--days", "4000")
    assert code == 2 and "--days must be between 1 and 3660" in err
    code, _, err = run_cli(home, "report", "--html", str(tmp_path / "missing" / "x.html"))
    assert code == 1 and "could not write" in err
