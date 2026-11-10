"""Pick a session label from a todo.txt file (http://todotxt.org format).

Tasks are numbered by line, starting at 1, the same way ``todo.sh`` numbers
them, so ``--task 3`` means the third line of the file.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

_DONE = re.compile(r"^x\s")
_DONE_PREFIX = re.compile(r"^x\s+(\d{4}-\d{2}-\d{2}(\s+|$))?")
_PRIORITY = re.compile(r"^\([A-Z]\)\s+")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+")
# key:value metadata such as due:2026-11-20 or pomodoros:3. The value may not
# start with "/" so URLs (https://...) stay in the text, and the key must
# start with a letter so times like 10:30 are not mistaken for tags.
_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[^\s:/][^\s:]*$")


TALLY_KEY = "pomodoros"
# Matched on raw bytes so the rest of the line (and file) is never re-encoded.
_TALLY = re.compile(rb"(?<!\S)pomodoros:(\d+)(?!\S)")
_ANY_TALLY = re.compile(rb"(?<!\S)pomodoros:\S*")
_BOM = b"\xef\xbb\xbf"


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


def _split_ending(line: bytes) -> tuple[bytes, bytes]:
    if line.endswith(b"\r\n"):
        return line[:-2], b"\r\n"
    if line.endswith((b"\n", b"\r")):
        return line[:-1], line[-1:]
    return line, b""


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` via a temp file in the same directory."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        except OSError:  # pragma: no cover - permissions are best effort
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def bump_tally(path: Path, task: TodoTask, by: int = 1) -> tuple[TodoTask, int]:
    """Add ``by`` to the ``pomodoros:N`` tag of ``task`` in ``path``.

    An existing tag is incremented in place; otherwise `` pomodoros:BY`` is
    appended to the end of the line. Every other byte of the file (other
    lines, tags, line endings, a BOM, a missing final newline) is kept as is,
    and the file is replaced atomically. The task is looked up by its line
    number, or, if that line changed, by its exact text when that is unique,
    so lines added above it while the timer ran do not break the update.

    Returns the task with its new ``raw`` text and the new count.
    """
    target = Path(path).expanduser().resolve()
    try:
        data = target.read_bytes()
    except FileNotFoundError:
        raise TodoError(f"todo file {path} does not exist") from None
    except OSError as exc:
        raise TodoError(f"could not read todo file {path}: {exc}") from None
    lines = data.splitlines(keepends=True)

    def text_of(index: int) -> str:
        body = _split_ending(lines[index])[0]
        if index == 0 and body.startswith(_BOM):
            body = body[len(_BOM):]
        return body.decode("utf-8", errors="replace")

    index = task.number - 1
    if not (0 <= index < len(lines) and text_of(index) == task.raw):
        matches = [i for i in range(len(lines)) if text_of(i) == task.raw]
        if len(matches) != 1:
            raise TodoError(f"task {task.number} changed in {path}; "
                            f"{TALLY_KEY} tag not updated")
        index = matches[0]

    body, ending = _split_ending(lines[index])
    bom = b""
    if index == 0 and body.startswith(_BOM):
        bom, body = _BOM, body[len(_BOM):]
    found = _TALLY.search(body)
    if found:
        count = int(found.group(1)) + by
        body = body[: found.start(1)] + str(count).encode("ascii") + body[found.end(1):]
    elif _ANY_TALLY.search(body):
        raise TodoError(f"task {task.number} has a {TALLY_KEY}: tag that is not a "
                        f"whole number; not updated")
    else:
        count = by
        head = body.rstrip(b" \t")
        body = head + f" {TALLY_KEY}:{count}".encode("ascii") + body[len(head):]
    lines[index] = bom + body + ending
    try:
        _write_atomic(target, b"".join(lines))
    except OSError as exc:
        raise TodoError(f"could not update todo file {path}: {exc}") from None
    new_raw = body.decode("utf-8", errors="replace")
    return replace(task, raw=new_raw), count
