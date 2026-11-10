import json

import pytest

from focusbell import config
from focusbell.log import read_sessions
from focusbell.todo import TodoError, read_task, task_label

TODO = """\
(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20
Reply to Sam about the budget @email

x 2026-11-05 2026-11-02 File expenses
Read https://example.org/paper +reading pomodoros:2
due:2026-12-01
"""

QUICK = ["start", "--seconds", "--work", "2", "--short", "1", "--long", "1",
         "--cycles", "1", "--no-bell"]


@pytest.fixture
def todo_file(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_text(TODO, encoding="utf-8")
    return path


def sessions(home):
    return read_sessions(home / "sessions.jsonl")


# ------------------------------------------------------------ parsing


@pytest.mark.parametrize(
    "line,label",
    [
        ("(A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20",
         "Write chapter 2 +thesis @desk"),
        ("Call mum", "Call mum"),
        ("  2026-11-01   spaced   out  ", "spaced out"),
        ("Read https://example.org/paper pomodoros:3", "Read https://example.org/paper"),
        ("(a) lowercase is not a priority", "(a) lowercase is not a priority"),
        ("Meet at 10:30 t:2026-11-10", "Meet at 10:30"),
    ],
)
def test_task_label_strips_metadata_but_keeps_projects(line, label):
    assert task_label(line) == label


def test_read_task_by_line_number(todo_file):
    task = read_task(todo_file, 1)
    assert task.number == 1
    assert task.label == "Write chapter 2 +thesis @desk"
    assert task.raw.startswith("(A) 2026-11-01")
    assert read_task(todo_file, 5).label == "Read https://example.org/paper +reading"


@pytest.mark.parametrize(
    "number,message",
    [
        (3, "line 3 of .* is empty"),
        (4, "task 4 is already done: x 2026-11-05"),
        (6, "task 6 has no description"),
        (7, "has 6 line\\(s\\), no task 7"),
        (0, "start at 1"),
    ],
)
def test_read_task_rejects_unusable_lines(todo_file, number, message):
    with pytest.raises(TodoError, match=message):
        read_task(todo_file, number)


def test_read_task_missing_file(tmp_path):
    with pytest.raises(TodoError, match="does not exist"):
        read_task(tmp_path / "nope.txt", 1)


def test_read_task_handles_bom_and_crlf(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes("﻿(B) First task\r\nSecond task\r\n".encode("utf-8"))
    assert read_task(path, 1).label == "First task"
    assert read_task(path, 2).raw == "Second task"


# ------------------------------------------------------------ config


def test_todo_file_config_key():
    assert config.DEFAULTS["todo_file"] == ""
    assert config.validate("todo_file", "  ~/todo.txt ") == "~/todo.txt"
    with pytest.raises(config.ConfigError, match="must be a path"):
        config.validate("todo_file", 3)
    with pytest.raises(config.ConfigError, match="single-line"):
        config.validate("todo_file", "a\nb")


def test_config_set_todo_file_stores_absolute_path(run, isolated_home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = run("config", "set", "todo_file", "todo.txt")
    assert code == 0
    stored = json.loads((isolated_home / "config.json").read_text(encoding="utf-8"))
    assert stored == {"todo_file": str(tmp_path / "todo.txt")}
    assert run("config", "get", "todo_file")[1] == str(tmp_path / "todo.txt") + "\n"
    assert run("config", "set", "todo_file", "")[0] == 0
    assert run("config", "get", "todo_file")[1] == "\n"


# ------------------------------------------------------------ start --task


def test_start_task_uses_cleaned_line_as_label(run, isolated_home, todo_file):
    code, out, err = run(*QUICK, "--task", "1", "--todo-file", str(todo_file))
    assert code == 0, err
    lines = out.splitlines()
    assert lines[1] == "Task 1: (A) 2026-11-01 Write chapter 2 +thesis @desk due:2026-11-20"
    assert "Work 1/1: 00:02 left  [Write chapter 2 +thesis @desk]" in out
    assert [s.label for s in sessions(isolated_home)] == ["Write chapter 2 +thesis @desk"]
    # The todo file itself is left untouched.
    assert todo_file.read_text(encoding="utf-8") == TODO


def test_start_task_reads_todo_file_from_config(run, isolated_home, todo_file):
    run("config", "set", "todo_file", str(todo_file))
    code, out, err = run(*QUICK, "--task", "2")
    assert code == 0, err
    assert "Task 2: Reply to Sam about the budget @email" in out
    assert sessions(isolated_home)[0].label == "Reply to Sam about the budget @email"


def test_todo_file_flag_beats_config(run, isolated_home, todo_file, tmp_path):
    other = tmp_path / "other.txt"
    other.write_text("Other list task\n", encoding="utf-8")
    run("config", "set", "todo_file", str(todo_file))
    code, _, _ = run(*QUICK, "--task", "1", "--todo-file", str(other))
    assert code == 0
    assert sessions(isolated_home)[0].label == "Other list task"


def test_start_task_without_todo_file_is_usage_error(run, isolated_home):
    code, out, err = run(*QUICK, "--task", "1")
    assert code == 2
    assert "--task needs a todo.txt" in err
    assert out == ""
    assert not (isolated_home / "sessions.jsonl").exists()


@pytest.mark.parametrize("number,message", [("4", "already done"), ("9", "no task 9")])
def test_start_bad_task_exits_2_before_timing(run, isolated_home, todo_file, number, message):
    code, out, err = run(*QUICK, "--task", number, "--todo-file", str(todo_file))
    assert code == 2
    assert message in err
    assert out == ""
    assert not (isolated_home / "sessions.jsonl").exists()


def test_task_and_label_are_mutually_exclusive(run, todo_file):
    code, _, _ = run(*QUICK, "--task", "1", "--label", "x", "--todo-file", str(todo_file))
    assert code == 2


@pytest.mark.parametrize("value", ["0", "-1", "two"])
def test_task_number_must_be_positive(run, value):
    assert run(*QUICK, "--task", value)[0] == 2


def test_todo_file_without_task_warns(run, isolated_home, todo_file):
    code, _, err = run(*QUICK, "--label", "plain", "--todo-file", str(todo_file))
    assert code == 0
    assert "--todo-file has no effect without --task" in err
    assert sessions(isolated_home)[0].label == "plain"
