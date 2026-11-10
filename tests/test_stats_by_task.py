import json
from datetime import date, timezone

import pytest

from focusbell.log import parse_record
from focusbell.stats import by_label
from focusbell.todo import TodoError, read_tasks

TODO = """\
(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Reply to Sam about the budget @email

x 2026-11-06 2026-11-02 File expenses
(B) Review PR 42 +focusbell pomodoros:2
x 2026-11-07 Review PR 42 +focusbell
"""


def record(start, minutes=25.0, label=None, status="completed"):
    return {"start": start, "minutes": minutes, "planned_minutes": 25.0,
            "label": label, "status": status}


LOG = [
    record("2026-11-04T09:00:00+00:00", label="File expenses"),
    record("2026-11-05T09:00:00+00:00", label="Write chapter 2 +thesis @desk"),
    record("2026-11-05T09:30:00+00:00", 12.0, "Write chapter 2 +thesis @desk", "interrupted"),
    record("2026-11-07T10:00:00+00:00", label="Write chapter 2 +thesis @desk"),
    record("2026-11-08T14:00:00+00:00", label="Review PR 42 +focusbell"),
    record("2026-11-09T08:00:00+00:00", label="standup"),
    record("2026-11-09T09:00:00+00:00", 18.0, None, "interrupted"),
    # Outside a 7-day window ending 2026-11-09:
    record("2026-10-20T09:00:00+00:00", 50.0, "Reply to Sam about the budget @email"),
]


def write_log(home, records):
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "sessions.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


@pytest.fixture
def todo_file(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_text(TODO, encoding="utf-8")
    return path


# ------------------------------------------------------------ read_tasks


def test_read_tasks_lists_open_and_done_with_line_numbers(todo_file):
    tasks = read_tasks(todo_file)
    assert [(t.number, t.label, t.done) for t in tasks] == [
        (1, "Write chapter 2 +thesis @desk", False),
        (2, "Reply to Sam about the budget @email", False),
        (4, "File expenses", True),  # completion and creation dates both dropped
        (5, "Review PR 42 +focusbell", False),
        (6, "Review PR 42 +focusbell", True),
    ]


def test_read_tasks_skips_lines_without_description(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_text("due:2026-12-01\n\nx 2026-11-01\nReal task\n", encoding="utf-8")
    assert [(t.number, t.label) for t in read_tasks(path)] == [(4, "Real task")]


def test_read_tasks_missing_file(tmp_path):
    with pytest.raises(TodoError, match="does not exist"):
        read_tasks(tmp_path / "missing.txt")


# ------------------------------------------------------------ by_label


def test_by_label_groups_window_and_sorts():
    sessions = [parse_record(r) for r in LOG]
    groups = by_label(sessions, date(2026, 11, 3), date(2026, 11, 9), timezone.utc)
    assert [(g.label, g.sessions, g.completed, g.minutes, g.last_day) for g in groups] == [
        ("Write chapter 2 +thesis @desk", 3, 2, 62.0, date(2026, 11, 7)),
        ("File expenses", 1, 1, 25.0, date(2026, 11, 4)),
        ("Review PR 42 +focusbell", 1, 1, 25.0, date(2026, 11, 8)),
        ("standup", 1, 1, 25.0, date(2026, 11, 9)),
        (None, 1, 0, 18.0, date(2026, 11, 9)),  # unlabelled always last
    ]


def test_by_label_uses_local_day_of_start():
    sessions = [parse_record(record("2026-11-09T23:30:00+00:00", label="late"))]
    plus2 = timezone(__import__("datetime").timedelta(hours=2))
    assert by_label(sessions, date(2026, 11, 9), date(2026, 11, 9), plus2) == []
    assert [g.label for g in by_label(sessions, date(2026, 11, 10), date(2026, 11, 10),
                                      plus2)] == ["late"]


# ------------------------------------------------------------ CLI


def test_stats_by_task_without_todo_file(run, isolated_home):
    write_log(isolated_home, LOG)
    code, out, err = run("stats", "--by", "task")
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == "Focus time by task, last 7 day(s) (2026-11-03 to 2026-11-09)"
    assert lines[2].split() == ["Task", "Completed", "Focus", "Share", "Last"]
    assert lines[4].split() == ["Write", "chapter", "2", "+thesis", "@desk",
                                "2/3", "1h", "02m", "40%", "2026-11-07"]
    assert lines[8].split() == ["(no", "label)", "0/1", "18m", "12%", "2026-11-09"]
    assert "Reply to Sam" not in out  # only in the log before the window
    assert "Total       2h 35m in 7 session(s) across 5 label(s)" in out
    assert "#" not in out and "No focus time yet" not in out


def test_stats_by_task_numbers_rows_from_todo_file(run, isolated_home, todo_file):
    write_log(isolated_home, LOG)
    code, out, err = run("stats", "--by", "task", "--todo-file", str(todo_file))
    assert code == 0, err
    rows = {line.split()[0]: line for line in out.splitlines()[4:9]}
    assert "Write chapter 2" in rows["1"]
    assert "File expenses" in rows["x4"]  # done task marked with x
    assert "Review PR 42" in rows["5"]  # the open line wins over the done duplicate
    assert out.splitlines()[0].startswith("Focus time by task")
    assert "-   standup" in out and "-   (no label)" in out
    assert out.rstrip().endswith("No focus time yet on open task(s) 2")


def test_stats_by_task_reads_todo_file_from_config(run, isolated_home, todo_file):
    write_log(isolated_home, LOG)
    run("config", "set", "todo_file", str(todo_file))
    code, out, _ = run("stats", "--by", "task", "--days", "30")
    assert code == 0
    assert "2   Reply to Sam about the budget @email" in out  # now inside the window
    assert "No focus time yet" not in out


def test_stats_by_task_bad_explicit_todo_file_is_usage_error(run, isolated_home, tmp_path):
    write_log(isolated_home, LOG)
    code, out, err = run("stats", "--by", "task", "--todo-file", str(tmp_path / "nope.txt"))
    assert code == 2
    assert "does not exist" in err
    assert out == ""


def test_stats_by_task_stale_config_todo_file_only_warns(run, isolated_home, tmp_path):
    write_log(isolated_home, LOG)
    run("config", "set", "todo_file", str(tmp_path / "gone.txt"))
    code, out, err = run("stats", "--by", "task")
    assert code == 0
    assert "showing labels without task numbers" in err
    assert "Write chapter 2" in out and "#" not in out


def test_stats_by_task_empty_period_still_lists_idle_tasks(run, todo_file):
    code, out, _ = run("stats", "--by", "task", "--todo-file", str(todo_file))
    assert code == 0
    assert "No sessions in this period." in out
    assert "No focus time yet on open task(s) 1, 2, 5" in out


def test_stats_by_task_shortens_long_labels(run, isolated_home):
    long = "Refactor " + "the parser " * 10
    write_log(isolated_home, [record("2026-11-09T08:00:00+00:00", label=long.strip())])
    _, out, _ = run("stats", "--by", "task")
    row = out.splitlines()[4]
    assert row.startswith("Refactor the parser") and "..." in row
    assert len(row.split("...")[0]) <= 48


def test_stats_default_view_unchanged_and_todo_file_warns(run, isolated_home, todo_file):
    write_log(isolated_home, LOG)
    code, out, err = run("stats", "--todo-file", str(todo_file))
    assert code == 0
    assert "Top labels" in out and "Focus time, last 7 day(s)" in out
    assert "--todo-file has no effect without --by task" in err


def test_stats_by_rejects_unknown_choice(run):
    assert run("stats", "--by", "week")[0] == 2
