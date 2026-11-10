import json
import os

import pytest

from focusbell import config, todo
from focusbell.log import read_sessions
from focusbell.todo import TodoError, TodoTask, bump_tally, read_task

QUICK = ["start", "--seconds", "--work", "2", "--short", "1", "--long", "1",
         "--no-bell"]


class InterruptAt:
    """A clock that raises KeyboardInterrupt the first time it passes ``at``."""

    def __init__(self, start=1_793_000_000.0, at=None):
        self.t = start
        self.at = at

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        if self.at is not None and self.t + seconds >= self.at:
            self.t = self.at
            raise KeyboardInterrupt
        self.t += seconds


def write(tmp_path, data: bytes, name="todo.txt"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# ------------------------------------------------------------ bump_tally


def test_appends_tag_and_keeps_every_other_byte(tmp_path):
    data = (b"\xef\xbb\xbf(A) 2026-11-01 Write chapter 2 +thesis due:2026-11-20\r\n"
            b"Reply to Sam caf\xc3\xa9 @email\r\n"
            b"\r\n"
            b"x 2026-11-05 File expenses\n"
            b"Latin-1 byte \xe9 stays\r\n"
            b"Last line, no newline")
    path = write(tmp_path, data)
    task = read_task(path, 2)
    new, count = bump_tally(path, task)
    assert count == 1
    assert new.raw == "Reply to Sam café @email pomodoros:1"
    assert path.read_bytes() == data.replace(
        b"Reply to Sam caf\xc3\xa9 @email\r\n",
        b"Reply to Sam caf\xc3\xa9 @email pomodoros:1\r\n")


def test_increments_existing_tag_in_place(tmp_path):
    data = b"Read paper pomodoros:9 +reading due:2026-12-01\nother\n"
    path = write(tmp_path, data)
    task = read_task(path, 1)
    task, count = bump_tally(path, task)
    assert count == 10
    task, count = bump_tally(path, task, by=2)
    assert count == 12
    assert path.read_bytes() == b"Read paper pomodoros:12 +reading due:2026-12-01\nother\n"
    # The label is the same before and after, so stats keep matching it.
    assert read_task(path, 1).label == "Read paper +reading"


def test_first_line_bom_and_trailing_spaces_preserved(tmp_path):
    path = write(tmp_path, b"\xef\xbb\xbfFirst task  \nSecond")
    bump_tally(path, read_task(path, 1))
    assert path.read_bytes() == b"\xef\xbb\xbfFirst task pomodoros:1  \nSecond"
    bump_tally(path, read_task(path, 2))
    assert path.read_bytes() == b"\xef\xbb\xbfFirst task pomodoros:1  \nSecond pomodoros:1"


def test_similar_tags_are_not_touched(tmp_path):
    path = write(tmp_path, b"Task xpomodoros:4 old-pomodoros:2\n")
    bump_tally(path, read_task(path, 1))
    assert path.read_bytes() == b"Task xpomodoros:4 old-pomodoros:2 pomodoros:1\n"


def test_non_numeric_tag_is_refused_and_file_untouched(tmp_path):
    data = b"Task pomodoros:lots\n"
    path = write(tmp_path, data)
    with pytest.raises(TodoError, match="not a whole number"):
        bump_tally(path, read_task(path, 1))
    assert path.read_bytes() == data


def test_task_moved_by_inserted_line_is_found_by_text(tmp_path):
    path = write(tmp_path, b"Alpha\nBeta\n")
    task = read_task(path, 2)
    path.write_bytes(b"New top line\nAlpha\nBeta\n")
    new, _ = bump_tally(path, task)
    assert path.read_bytes() == b"New top line\nAlpha\nBeta pomodoros:1\n"
    assert new.number == 2  # still reported with the number the user picked


@pytest.mark.parametrize("edited", [b"Alpha\nBeta edited\n", b"Beta\nAlpha\nBeta\n"])
def test_changed_or_ambiguous_task_is_not_updated(tmp_path, edited):
    path = write(tmp_path, b"Alpha\nBeta\n")
    task = read_task(path, 2)
    path.write_bytes(edited)
    with pytest.raises(TodoError, match="changed"):
        bump_tally(path, task)
    assert path.read_bytes() == edited


def test_missing_file(tmp_path):
    with pytest.raises(TodoError, match="does not exist"):
        bump_tally(tmp_path / "gone.txt", TodoTask(1, "x", "x"))


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path, monkeypatch):
    data = b"Alpha\nBeta\n"
    path = write(tmp_path, data)

    def boom(src, dst):
        raise PermissionError("locked by editor")

    monkeypatch.setattr(todo.os, "replace", boom)
    with pytest.raises(TodoError, match="could not update.*locked by editor"):
        bump_tally(path, read_task(path, 1))
    assert path.read_bytes() == data
    assert sorted(p.name for p in tmp_path.iterdir()) == ["todo.txt"]


def test_symlinked_todo_file_keeps_the_link(tmp_path):
    real = write(tmp_path, b"Alpha\n", "real.txt")
    link = tmp_path / "todo.txt"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    bump_tally(link, read_task(link, 1))
    assert link.is_symlink()
    assert real.read_bytes() == b"Alpha pomodoros:1\n"


# ------------------------------------------------------------ config


def test_tally_config_key():
    assert config.DEFAULTS["tally"] is False
    assert config.validate("tally", "on") is True
    with pytest.raises(config.ConfigError, match="true or false"):
        config.validate("tally", "maybe")


# ------------------------------------------------------------ start --tally


def test_start_tally_bumps_once_per_completed_block(run, isolated_home, tmp_path):
    data = b"(A) Write chapter 2 +thesis\r\nReview PR pomodoros:3\r\nx done thing\r\n"
    path = write(tmp_path, data)
    code, out, err = run(*QUICK, "--cycles", "2", "--task", "2", "--todo-file", str(path),
                         "--tally")
    assert code == 0, err
    assert err == ""
    assert out.splitlines()[-1] == f"Task 2: pomodoros:5 (+2) in {path}"
    assert path.read_bytes() == data.replace(b"pomodoros:3", b"pomodoros:5")
    # The session log is unchanged in format and keeps the stable label.
    records = [json.loads(line) for line in
               (isolated_home / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["label"] for r in records] == ["Review PR", "Review PR"]
    assert all(set(r) == {"start", "end", "minutes", "planned_minutes", "label", "status"}
               for r in records)


def test_start_without_tally_leaves_file_alone(run, tmp_path):
    data = b"Alpha\n"
    path = write(tmp_path, data)
    code, out, _ = run(*QUICK, "--cycles", "1", "--task", "1", "--todo-file", str(path))
    assert code == 0
    assert path.read_bytes() == data
    assert "pomodoros" not in out


def test_tally_config_key_turns_it_on_and_flag_turns_it_off(run, tmp_path):
    path = write(tmp_path, b"Alpha\n")
    run("config", "set", "tally", "true")
    run(*QUICK, "--cycles", "1", "--task", "1", "--todo-file", str(path))
    assert path.read_bytes() == b"Alpha pomodoros:1\n"
    run(*QUICK, "--cycles", "1", "--task", "1", "--todo-file", str(path), "--no-tally")
    assert path.read_bytes() == b"Alpha pomodoros:1\n"


def test_interrupted_block_is_not_counted(run, isolated_home, tmp_path):
    path = write(tmp_path, b"Alpha\n")
    # Work 2s, short 1s, then Ctrl+C one second into the second work block.
    clk = InterruptAt(at=1_793_000_000.0 + 4)
    code, out, err = run(*QUICK, "--cycles", "2", "--task", "1", "--todo-file", str(path),
                         "--tally", clock=clk)
    assert code == 130
    assert path.read_bytes() == b"Alpha pomodoros:1\n"
    assert "Task 1: pomodoros:1 (+1)" in out
    statuses = [s.status for s in read_sessions(isolated_home / "sessions.jsonl")]
    assert statuses == ["completed", "interrupted"]


def test_task_edited_during_session_warns_after_timer(run, tmp_path):
    path = write(tmp_path, b"Alpha\n")

    class EditingClock(InterruptAt):
        def sleep(self, seconds):
            path.write_bytes(b"Alpha, reworded\n")
            super().sleep(seconds)

    code, out, err = run(*QUICK, "--cycles", "2", "--task", "1", "--todo-file", str(path),
                         "--tally", clock=EditingClock())
    assert code == 0
    assert path.read_bytes() == b"Alpha, reworded\n"
    assert "pomodoros" not in out
    assert err.count("warning") == 1
    assert "task 1 changed" in err


def test_tally_without_task_warns(run, tmp_path):
    code, _, err = run(*QUICK, "--cycles", "1", "--label", "x", "--tally")
    assert code == 0
    assert "--tally has no effect without --task" in err
