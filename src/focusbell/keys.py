"""Non-blocking single-key reading from the terminal, standard library only.

``key_reader()`` is a context manager that yields a ``poll()`` function, or
``None`` when keys cannot be read (stdin is not a terminal, or the platform has
neither ``msvcrt`` nor ``termios``). ``poll()`` never blocks: it returns the
next pressed key as a lowercase one-character string, or ``None``.

On POSIX the terminal is put in cbreak mode (no line buffering, no echo, but
Ctrl+C still sends SIGINT) and restored on exit, even after an exception.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, TextIO

Poll = Callable[[], Optional[str]]


def _isatty(stream: Optional[TextIO]) -> bool:
    try:
        return stream is not None and bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _windows_poll() -> Poll:
    import msvcrt

    def poll() -> Optional[str]:
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # arrow/function keys arrive as two codes
                msvcrt.getwch()
                continue
            return ch.lower()
        return None

    return poll


@contextmanager
def key_reader(stream: Optional[TextIO] = None) -> Iterator[Optional[Poll]]:
    stream = sys.stdin if stream is None else stream
    if not _isatty(stream):
        yield None
        return
    if sys.platform == "win32":
        yield _windows_poll()
        return
    try:
        import select
        import termios
        import tty
    except ImportError:  # pragma: no cover - exotic platforms
        yield None
        return
    try:
        fd = stream.fileno()
        saved = termios.tcgetattr(fd)
    except (OSError, ValueError, termios.error):
        yield None
        return

    def poll() -> Optional[str]:
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            return None
        data = os.read(fd, 1)
        return data.decode("utf-8", "replace").lower() if data else None

    try:
        tty.setcbreak(fd)
        yield poll
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
