"""Pick a session label from a todo.txt file (http://todotxt.org format).

Tasks are numbered by line, starting at 1, the same way ``todo.sh`` numbers
them, so ``--task 3`` means the third line of the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DONE = re.compile(r"^x\s")
_DONE_PREFIX = re.compile(r"^x\s+(\d{4}-\d{2}-\d{2}(\s+|$))?")
_PRIORITY = re.compile(r"^\([A-Z]\)\s+")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+")
# key:value metadata such as due:2026-11-20 or pomodoros:3. The value may not
# start with "/" so URLs (https://...) stay in the text, and the key must
# start with a letter so times like 10:30 are not mistaken for tags.
_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[^\s:/][^\s:]*$")


class TodoError(ValueError):
    """The file cannot be read, or line N is not a usable open task."""


@dataclass(frozen=True)
class TodoTask:
    number: int
    raw: str  # the line as written, without the newline
    label: str  # description with priority, creation date and key:value tags removed
    done: bool = False  # the line starts with "x " (completed task)


def task_label(line: str) -> str:
    """Turn a todo.txt line into a session label.

    Drops the priority ``(A)``, the creation date and ``key:value`` tags, so
    the label stays the same when a due date or counter changes. ``+project``
    and ``@context`` words are kept.
    """
    text = line.strip()
    text = _PRIORITY.sub("", text, count=1)
    text = _DATE.sub("", text, count=1)
    words = [w for w in text.split() if not _TAG.match(w)]
    return " ".join(words)


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        raise TodoError(f"todo file {path} does not exist") from None
    except OSError as exc:
        raise TodoError(f"could not read todo file {path}: {exc}") from None
    return text.splitlines()


def read_tasks(path: Path) -> list[TodoTask]:
    """Every task in ``path``, open and done, keeping todo.sh line numbers.

    Empty lines and lines without a description are left out. A done task's
    label is computed after dropping the ``x`` and its completion date, so it
    matches the label the task had while it was open.
    """
    tasks = []
    for number, raw in enumerate(_read_lines(path), start=1):
        text = raw.strip()
        done = bool(_DONE.match(text))
        label = task_label(_DONE_PREFIX.sub("", text, count=1) if done else text)
        if label:
            tasks.append(TodoTask(number, raw, label, done))
    return tasks


def read_task(path: Path, number: int) -> TodoTask:
    """Return open task ``number`` (1-based line number) from ``path``."""
    if number < 1:
        raise TodoError(f"task numbers start at 1, got {number}")
    lines = _read_lines(path)
    if number > len(lines):
        raise TodoError(f"{path} has {len(lines)} line(s), no task {number}")
    raw = lines[number - 1]
    if not raw.strip():
        raise TodoError(f"line {number} of {path} is empty")
    if _DONE.match(raw.strip()):
        raise TodoError(f"task {number} is already done: {raw.strip()}")
    label = task_label(raw)
    if not label:
        raise TodoError(f"task {number} has no description: {raw.strip()}")
    return TodoTask(number, raw, label)
